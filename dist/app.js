(function () {
  "use strict";

  var session = null;
  var state = null;
  var revision = 0;
  var saveQueue = Promise.resolve();
  var saveFailed = false;
  var editIndex = -1;
  var characterIndex = -1;
  var expiryTimer = null;
  var statuses = [
    "Script draft",
    "60s script ready",
    "References approved",
    "Assets generated",
    "Editing",
    "Ready for review",
    "Approved",
    "Published"
  ];

  /** Return one element by id. */
  function byId(id) {
    return document.getElementById(id);
  }

  /** Escape untrusted text before including it in an HTML fragment. */
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[character];
    });
  }

  /** Return an HTTP or HTTPS link, or an empty string for unsafe input. */
  function safeLink(value) {
    try {
      var url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (error) {
      return "";
    }
  }

  /** Show a concise success or failure message beside a form. */
  function setStatus(element, message, kind) {
    element.textContent = message || "";
    element.classList.toggle("error", kind === "error");
    element.classList.toggle("success", kind === "success");
  }

  /** Send one JSON API request and surface the server's safe error message. */
  async function api(path, options) {
    var requestOptions = Object.assign({}, options || {});
    requestOptions.headers = Object.assign({}, requestOptions.headers || {});
    if (requestOptions.body && typeof requestOptions.body !== "string") {
      requestOptions.headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(requestOptions.body);
    }
    if (session && requestOptions.method && requestOptions.method !== "GET") {
      requestOptions.headers["X-CSRF-Token"] = session.csrfToken;
    }
    var response = await fetch(path, requestOptions);
    var payload = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      var error = new Error(payload.error || "Request failed.");
      error.status = response.status;
      if (response.status === 401 && path !== "/api/login") {
        showSignedOut("Your session has expired. Sign in again.");
      }
      throw error;
    }
    return payload;
  }

  /** Build a new fictional workspace for an account with no saved data. */
  function defaultProject() {
    return {
      id: "sample-series",
      title: "Sample series",
      genre: "AI microdrama",
      description: "A fictional starter project. Replace or edit it for your own story.",
      stage: "Planning",
      episodes: structuredClone(seed.episodes),
      characters: structuredClone(seed.characters),
      gates: structuredClone(seed.gates)
    };
  }

  /** Normalize current and older JSON exports to the current workspace shape. */
  function migrateWorkspace(value) {
    if (value && Array.isArray(value.projects) && value.projects.length) {
      value.projects.forEach(function (project) {
        project.episodes = project.episodes || [];
        project.characters = project.characters || [];
        project.gates = project.gates || [];
      });
      value.activeId = value.activeId || value.projects[0].id;
      return value;
    }
    if (value && Array.isArray(value.episodes)) {
      return {
        projects: [
          Object.assign(defaultProject(), {
            id: "imported-series",
            title: "Imported series",
            episodes: value.episodes,
            characters: value.characters || [],
            gates: value.gates || []
          })
        ],
        activeId: "imported-series"
      };
    }
    return {projects: [defaultProject()], activeId: "sample-series"};
  }

  /** Apply a theme and optionally persist it for the authenticated account. */
  async function applyTheme(theme, persist) {
    var selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    document.querySelector('meta[name="theme-color"]').content =
      selected === "dark" ? "#07111f" : "#eef8ff";
    document.querySelectorAll(".theme-glyph").forEach(function (glyph) {
      glyph.textContent = selected === "dark" ? "☀" : "☾";
    });
    document.querySelectorAll("#themeToggle,#loginThemeToggle").forEach(function (button) {
      var label = selected === "dark" ? "Use light theme" : "Use dark theme";
      button.setAttribute("aria-label", label);
      button.title = label;
    });
    if (!session) {
      try {
        localStorage.setItem("aics_public_theme", selected);
      } catch (error) {
        return;
      }
      return;
    }
    session.user.theme = selected;
    if (persist) {
      try {
        var result = await api("/api/account", {
          method: "PUT",
          body: {theme: selected}
        });
        session.user = result.user;
      } catch (error) {
        setStatus(byId("profileStatus"), error.message, "error");
      }
    }
  }

  /** Toggle between the light and dark themes. */
  function toggleTheme() {
    var nextTheme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(nextTheme, Boolean(session));
  }

  /** Populate footer values from the server's single version source. */
  function updateFooter(payload) {
    byId("footerAppName").textContent = payload.appName || "AI Content Studio";
    byId("footerVersion").textContent = payload.version ? "v" + payload.version : "";
    byId("footerYear").textContent = String(new Date().getFullYear());
  }

  /** Schedule a clear sign-out message at the fixed server session expiry. */
  function scheduleExpiry() {
    if (expiryTimer) {
      window.clearTimeout(expiryTimer);
    }
    if (!session) {
      return;
    }
    var delay = Math.max(0, session.expiresAt * 1000 - Date.now());
    expiryTimer = window.setTimeout(function () {
      if (session && session.expiresAt * 1000 > Date.now()) {
        scheduleExpiry();
      } else {
        showSignedOut("Your session expired. Sign in again.");
      }
    }, Math.min(delay, 2147483647));
  }

  /** Display the login view and clear client-side authenticated state. */
  function showSignedOut(message) {
    session = null;
    state = null;
    revision = 0;
    saveFailed = false;
    byId("appView").classList.add("hidden");
    byId("authView").classList.remove("hidden");
    byId("loginPassword").value = "";
    setStatus(byId("loginStatus"), message || "", message ? "error" : "");
    byId("registrationPrompt").classList.toggle(
      "hidden",
      !byId("registrationPrompt").dataset.enabled
    );
    byId("registerForm").classList.add("hidden");
    byId("loginForm").classList.remove("hidden");
    byId("loginUsername").focus();
  }

  /** Populate authenticated account labels and reveal role-specific navigation. */
  function populateAccount() {
    byId("sideUserName").textContent = session.user.displayName;
    byId("sideUserRole").textContent =
      session.user.role === "admin" ? "Administrator" : "Private workspace";
    byId("accountUsername").value = session.user.username;
    byId("accountDisplayName").value = session.user.displayName;
    byId("adminNav").classList.toggle("hidden", session.user.role !== "admin");
  }

  /** Load the authenticated user's workspace and seed it only when empty. */
  async function loadWorkspace() {
    var loaded = await api("/api/workspace");
    revision = loaded.revision;
    state = loaded.data ? migrateWorkspace(loaded.data) : migrateWorkspace(null);
    saveQueue = Promise.resolve();
    saveFailed = false;
    if (!loaded.data) {
      persist();
    } else {
      byId("syncStatus").textContent = "Saved to your private workspace";
    }
    render();
  }

  /** Reveal the authenticated shell and initialize its private data. */
  async function showAuthenticated(payload) {
    session = payload;
    byId("authView").classList.add("hidden");
    byId("appView").classList.remove("hidden");
    applyTheme(session.user.theme, false);
    populateAccount();
    scheduleExpiry();
    await loadWorkspace();
    goTo("overview");
  }

  /** Return the selected project, falling back to the first project. */
  function activeProject() {
    return (
      state.projects.find(function (project) {
        return project.id === state.activeId;
      }) || state.projects[0]
    );
  }

  /** Queue a workspace snapshot so rapid edits retain optimistic revision order. */
  function persist() {
    if (saveFailed || !session) {
      return;
    }
    var snapshot = structuredClone(state);
    byId("syncStatus").textContent = "Saving…";
    saveQueue = saveQueue
      .then(function () {
        return api("/api/workspace", {
          method: "PUT",
          body: {revision: revision, data: snapshot}
        });
      })
      .then(function (result) {
        revision = result.revision;
        byId("syncStatus").textContent = "Saved to your private workspace";
      })
      .catch(function (error) {
        saveFailed = true;
        byId("syncStatus").textContent =
          "Save failed. Export a backup, then reload before editing.";
        window.alert(
          "Your changes could not be saved: " +
            error.message +
            " Export a backup before reloading."
        );
      });
  }

  /** Activate one application section and load admin data only when needed. */
  function goTo(tab) {
    document.querySelectorAll(".nav button,.section").forEach(function (element) {
      element.classList.remove("active");
    });
    var navButton = document.querySelector('.nav button[data-tab="' + tab + '"]');
    if (navButton) {
      navButton.classList.add("active");
    }
    var section = byId(tab);
    if (section) {
      section.classList.add("active");
    }
    byId("primaryNav").classList.remove("open");
    byId("navToggle").setAttribute("aria-expanded", "false");
    if (tab === "admin" && session.user.role === "admin") {
      loadAdmin();
    }
    render();
    byId("mainContent").focus({preventScroll: true});
  }

  /** Render dashboard counts and private project, episode, and character cards. */
  function render() {
    if (!state) {
      return;
    }
    var project = activeProject();
    byId("projectCount").textContent = String(state.projects.length);
    byId("episodeCount").textContent = String(
      state.projects.reduce(function (total, item) {
        return total + item.episodes.length;
      }, 0)
    );
    byId("readyCount").textContent = String(
      state.projects.reduce(function (total, item) {
        return (
          total +
          item.episodes.filter(function (episode) {
            return ["Approved", "Published"].includes(episode.status);
          }).length
        );
      }, 0)
    );
    byId("sheetCount").textContent = String(
      state.projects.reduce(function (total, item) {
        return (
          total +
          item.characters.filter(function (character) {
            return character.state === "Reference approved";
          }).length
        );
      }, 0)
    );

    var projects = state.projects
      .map(function (item) {
        return (
          '<article class="card projectcard">' +
          '<div class="kicker">' +
          escapeHtml(item.genre || "New project") +
          "</div><h3>" +
          escapeHtml(item.title) +
          "</h3><p>" +
          escapeHtml(item.description || "Your next creative world begins here.") +
          '</p><div class="cardfooter"><span class="badge ' +
          (item.stage === "Published" ? "green" : "amber") +
          '">' +
          escapeHtml(item.stage || "Planning") +
          " · " +
          item.episodes.length +
          ' episodes</span><button class="btn" type="button" data-open="' +
          escapeHtml(item.id) +
          '">Open project</button></div></article>'
        );
      })
      .join("");
    byId("homeProjects").innerHTML = projects;
    byId("projectGrid").innerHTML = projects;
    byId("activeTitle").textContent = project.title;
    byId("activeMeta").textContent =
      (project.genre || "Untitled format") +
      " · " +
      project.episodes.length +
      " episodes · " +
      (project.stage || "Planning");
    byId("characterTitle").textContent = project.title;

    byId("episodeGrid").innerHTML = project.episodes.length
      ? project.episodes
          .map(function (episode, index) {
            var meter = Math.max(
              9,
              (statuses.indexOf(episode.status) + 1) * 12
            );
            return (
              '<article class="card"><div class="kicker">' +
              escapeHtml(episode.id) +
              " · " +
              escapeHtml(episode.duration || 60) +
              " seconds</div><h3>" +
              escapeHtml(episode.title) +
              "</h3><p>" +
              escapeHtml(episode.hook) +
              '</p><progress class="meter" max="100" value="' +
              meter +
              '">' +
              meter +
              '%</progress><div class="cardfooter"><span class="badge ' +
              (["Approved", "Published"].includes(episode.status)
                ? "green"
                : "amber") +
              '">' +
              escapeHtml(episode.status || "Script draft") +
              '</span><button class="btn" type="button" data-edit="' +
              index +
              '">Open script</button></div></article>'
            );
          })
          .join("")
      : '<div class="card empty"><h3>No episodes yet</h3><p>Add the first episode to begin its script.</p></div>';

    byId("characterGrid").innerHTML = project.characters.length
      ? project.characters
          .map(function (character, index) {
            var reference = safeLink(character.link);
            return (
              '<article class="card"><div class="kicker">' +
              escapeHtml(character.role || "Character") +
              " · " +
              escapeHtml(character.age || "") +
              "</div><h3>" +
              escapeHtml(character.name) +
              "</h3><p>" +
              escapeHtml(character.look) +
              '</p><div class="cardfooter"><span class="badge ' +
              (character.state === "Reference approved" ? "green" : "amber") +
              '">' +
              escapeHtml(character.state || "Written canon only") +
              '</span><button class="btn" type="button" data-character="' +
              index +
              '">Edit</button></div>' +
              (reference
                ? '<p><a href="' +
                  escapeHtml(reference) +
                  '" target="_blank" rel="noopener noreferrer">Reference ↗</a></p>'
                : "") +
              "</article>"
            );
          })
          .join("")
      : '<div class="card empty"><h3>No characters yet</h3><p>Add a cast member or recurring asset.</p></div>';
  }

  /** Open the episode editor for one project episode. */
  function openEpisode(index) {
    editIndex = index;
    var episode = activeProject().episodes[index];
    byId("modalKicker").textContent = episode.id;
    byId("modalTitle").textContent = episode.title;
    byId("eTitle").value = episode.title;
    byId("hook").value = episode.hook || "";
    byId("status").value = episode.status || "Script draft";
    byId("duration").value = episode.duration || 60;
    byId("script").value = episode.script || "";
    byId("assetLink").value = episode.assetLink || "";
    byId("editor").showModal();
  }

  /** Open the character editor for a new or existing character. */
  function openCharacter(index) {
    characterIndex = index;
    var character =
      index >= 0
        ? activeProject().characters[index]
        : {
            name: "",
            role: "",
            age: "",
            look: "",
            state: "Written canon only",
            link: ""
          };
    byId("characterModalTitle").textContent =
      index >= 0 ? "Edit character" : "Add character";
    byId("cName").value = character.name;
    byId("cRole").value = character.role;
    byId("cAge").value = character.age;
    byId("cLook").value = character.look;
    byId("cState").value = character.state;
    byId("cLink").value = character.link || "";
    byId("characterDialog").showModal();
  }

  /** Render the administrator's user list with safe role and access controls. */
  function renderUsers(users) {
    byId("userList").innerHTML = users
      .map(function (user) {
        return (
          '<article class="user-row" data-user-row="' +
          user.id +
          '"><div class="user-meta"><strong>' +
          escapeHtml(user.displayName) +
          "</strong><span>@" +
          escapeHtml(user.username) +
          '</span></div><label class="field">Role<select data-user-role>' +
          '<option value="user"' +
          (user.role === "user" ? " selected" : "") +
          ">User</option>" +
          '<option value="admin"' +
          (user.role === "admin" ? " selected" : "") +
          ">Admin</option></select></label>" +
          '<label class="switch-row"><input type="checkbox" data-user-active' +
          (user.active ? " checked" : "") +
          "><span>Active</span></label>" +
          '<button class="btn" type="button" data-save-user>Save</button></article>'
        );
      })
      .join("");
  }

  /** Load registration policy and account metadata for the admin section. */
  async function loadAdmin() {
    if (!session || session.user.role !== "admin") {
      return;
    }
    try {
      var results = await Promise.all([
        api("/api/admin/users"),
        api("/api/admin/settings")
      ]);
      renderUsers(results[0].users);
      byId("registrationEnabled").checked =
        results[1].registrationEnabled;
    } catch (error) {
      setStatus(byId("adminSettingsStatus"), error.message, "error");
    }
  }

  /** Update footer tool cards that contain only public fictional guidance. */
  function renderTools() {
    var tools = [
      ["ChatGPT", "Story bible, scripts, prompts, and optional image references."],
      ["Google Flow", "Image-to-video experiments. Check current credit and export terms."],
      ["Google AI Studio", "Text-to-speech tests. Verify pronunciation, timing, and current limits."],
      ["CapCut", "Assemble clips, effects, music, and captions. Check export licensing."],
      ["Kdenlive", "Open-source editing fallback and clean master exports."]
    ];
    byId("toolGrid").innerHTML = tools
      .map(function (tool) {
        return (
          '<article class="card"><div class="kicker">Production tool</div><h3>' +
          escapeHtml(tool[0]) +
          "</h3><p>" +
          escapeHtml(tool[1]) +
          "</p></article>"
        );
      })
      .join("");
  }

  /** Bootstrap public metadata, theme preference, and the current session. */
  async function bootstrap() {
    renderTools();
    byId("footerYear").textContent = String(new Date().getFullYear());
    var payload;
    try {
      payload = await api("/api/session");
    } catch (error) {
      updateFooter({appName: "AI Content Studio", version: ""});
      showSignedOut("The studio server is unavailable. Try again shortly.");
      return;
    }
    updateFooter(payload);
    byId("registrationPrompt").dataset.enabled = payload.registrationEnabled
      ? "true"
      : "";
    if (payload.authenticated) {
      await showAuthenticated(payload);
      return;
    }
    var publicTheme = "dark";
    try {
      publicTheme = localStorage.getItem("aics_public_theme") || "dark";
    } catch (error) {
      publicTheme = "dark";
    }
    applyTheme(publicTheme, false);
    showSignedOut("");
  }

  // Wire public authentication and theme controls.
  byId("loginThemeToggle").addEventListener("click", toggleTheme);
  byId("themeToggle").addEventListener("click", toggleTheme);
  byId("showRegister").addEventListener("click", function () {
    byId("loginForm").classList.add("hidden");
    byId("registrationPrompt").classList.add("hidden");
    byId("registerForm").classList.remove("hidden");
    byId("registerName").focus();
  });
  byId("hideRegister").addEventListener("click", function () {
    byId("registerForm").classList.add("hidden");
    byId("loginForm").classList.remove("hidden");
    byId("registrationPrompt").classList.remove("hidden");
    byId("loginUsername").focus();
  });
  byId("loginForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    setStatus(byId("loginStatus"), "Signing in…", "");
    try {
      var payload = await api("/api/login", {
        method: "POST",
        body: {
          username: byId("loginUsername").value.trim(),
          password: byId("loginPassword").value
        }
      });
      updateFooter(payload);
      await showAuthenticated(payload);
      byId("loginForm").reset();
    } catch (error) {
      setStatus(byId("loginStatus"), error.message, "error");
    }
  });
  byId("registerForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    setStatus(byId("registerStatus"), "Creating your workspace…", "");
    try {
      var payload = await api("/api/register", {
        method: "POST",
        body: {
          displayName: byId("registerName").value.trim(),
          username: byId("registerUsername").value.trim(),
          password: byId("registerPassword").value
        }
      });
      updateFooter(payload);
      await showAuthenticated(payload);
      byId("registerForm").reset();
    } catch (error) {
      setStatus(byId("registerStatus"), error.message, "error");
    }
  });
  byId("logout").addEventListener("click", async function () {
    try {
      await api("/api/logout", {method: "POST", body: {}});
    } catch (error) {
      if (error.status !== 401) {
        window.alert(error.message);
      }
    }
    showSignedOut("You have been signed out.");
  });

  // Wire responsive navigation and delegated project actions.
  byId("navToggle").addEventListener("click", function () {
    var nav = byId("primaryNav");
    var open = nav.classList.toggle("open");
    byId("navToggle").setAttribute("aria-expanded", String(open));
  });
  document.querySelectorAll(".nav button").forEach(function (button) {
    button.addEventListener("click", function () {
      goTo(button.dataset.tab);
    });
  });
  document.body.addEventListener("click", function (event) {
    var goButton = event.target.closest("[data-go]");
    if (goButton) {
      goTo(goButton.dataset.go);
    }
    var newButton = event.target.closest("[data-new]");
    if (newButton) {
      byId("projectDialog").showModal();
    }
    var openButton = event.target.closest("[data-open]");
    if (openButton) {
      state.activeId = openButton.dataset.open;
      persist();
      goTo("episodes");
    }
  });

  // Wire project, episode, and character editors.
  document.querySelectorAll("dialog [data-cancel]").forEach(function (button) {
    button.addEventListener("click", function () {
      button.closest("dialog").close("cancel");
    });
  });
  byId("newProject").addEventListener("click", function () {
    byId("projectDialog").showModal();
  });
  byId("projectForm").addEventListener("submit", function () {
    var title = byId("pTitle").value.trim();
    var id = "p-" + crypto.randomUUID();
    state.projects.push({
      id: id,
      title: title,
      genre: byId("pGenre").value.trim(),
      description: byId("pDescription").value.trim(),
      stage: "Planning",
      episodes: [],
      characters: [],
      gates: []
    });
    state.activeId = id;
    persist();
    byId("projectForm").reset();
    goTo("episodes");
  });
  byId("episodeGrid").addEventListener("click", function (event) {
    var button = event.target.closest("[data-edit]");
    if (button) {
      openEpisode(Number(button.dataset.edit));
    }
  });
  byId("addEpisode").addEventListener("click", function () {
    var project = activeProject();
    var id = "EP" + String(project.episodes.length + 1).padStart(2, "0");
    project.episodes.push({
      id: id,
      title: "Untitled episode",
      hook: "",
      status: "Script draft",
      duration: 60,
      script: "",
      assetLink: ""
    });
    persist();
    render();
    openEpisode(project.episodes.length - 1);
  });
  byId("editForm").addEventListener("submit", function () {
    var episode = activeProject().episodes[editIndex];
    if (!episode) {
      return;
    }
    episode.title = byId("eTitle").value.trim();
    episode.hook = byId("hook").value.trim();
    episode.status = byId("status").value;
    episode.duration = Number(byId("duration").value) || 60;
    episode.script = byId("script").value;
    episode.assetLink = byId("assetLink").value.trim();
    persist();
    render();
  });
  byId("addCharacter").addEventListener("click", function () {
    openCharacter(-1);
  });
  byId("characterGrid").addEventListener("click", function (event) {
    var button = event.target.closest("[data-character]");
    if (button) {
      openCharacter(Number(button.dataset.character));
    }
  });
  byId("characterForm").addEventListener("submit", function () {
    var character = {
      name: byId("cName").value.trim(),
      role: byId("cRole").value.trim(),
      age: byId("cAge").value.trim(),
      look: byId("cLook").value.trim(),
      state: byId("cState").value,
      link: byId("cLink").value.trim()
    };
    if (characterIndex < 0) {
      activeProject().characters.push(character);
    } else {
      activeProject().characters[characterIndex] = character;
    }
    persist();
    render();
  });

  // Wire portable backups without sending file content outside this server.
  byId("export").addEventListener("click", function () {
    var anchor = document.createElement("a");
    var url = URL.createObjectURL(
      new Blob([JSON.stringify(state, null, 2)], {type: "application/json"})
    );
    anchor.href = url;
    anchor.download = "ai-content-studio-backup.json";
    anchor.click();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  });
  byId("import").addEventListener("click", function () {
    byId("file").click();
  });
  byId("file").addEventListener("change", async function (event) {
    var file = event.target.files && event.target.files[0];
    if (!file) {
      return;
    }
    try {
      var imported = migrateWorkspace(JSON.parse(await file.text()));
      if (
        !Array.isArray(imported.projects) ||
        !imported.projects.every(function (project) {
          return (
            Array.isArray(project.episodes) &&
            Array.isArray(project.characters)
          );
        })
      ) {
        throw new Error("Invalid");
      }
      if (
        window.confirm(
          "Replace every project in your private workspace with this backup?"
        )
      ) {
        state = imported;
        persist();
        render();
        goTo("overview");
      }
    } catch (error) {
      window.alert("This is not a valid AI Content Studio backup.");
    }
    event.target.value = "";
  });

  // Wire account profile and password changes.
  byId("profileForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    setStatus(byId("profileStatus"), "Saving…", "");
    try {
      var result = await api("/api/account", {
        method: "PUT",
        body: {displayName: byId("accountDisplayName").value.trim()}
      });
      session.user = result.user;
      populateAccount();
      setStatus(byId("profileStatus"), "Profile saved.", "success");
    } catch (error) {
      setStatus(byId("profileStatus"), error.message, "error");
    }
  });
  byId("passwordForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    setStatus(byId("passwordStatus"), "Changing password…", "");
    try {
      var result = await api("/api/account", {
        method: "PUT",
        body: {
          currentPassword: byId("currentPassword").value,
          newPassword: byId("newPassword").value
        }
      });
      byId("passwordForm").reset();
      showSignedOut(result.message || "Password changed. Sign in again.");
    } catch (error) {
      setStatus(byId("passwordStatus"), error.message, "error");
    }
  });

  // Wire administrator-only registration and user controls.
  byId("registrationSettingsForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    setStatus(byId("adminSettingsStatus"), "Saving…", "");
    try {
      var result = await api("/api/admin/settings", {
        method: "PUT",
        body: {registrationEnabled: byId("registrationEnabled").checked}
      });
      byId("registrationPrompt").dataset.enabled =
        result.registrationEnabled ? "true" : "";
      setStatus(byId("adminSettingsStatus"), "Registration setting saved.", "success");
    } catch (error) {
      setStatus(byId("adminSettingsStatus"), error.message, "error");
    }
  });
  byId("userList").addEventListener("click", async function (event) {
    var button = event.target.closest("[data-save-user]");
    if (!button) {
      return;
    }
    var row = button.closest("[data-user-row]");
    button.disabled = true;
    try {
      await api("/api/admin/users/" + row.dataset.userRow, {
        method: "PUT",
        body: {
          role: row.querySelector("[data-user-role]").value,
          active: row.querySelector("[data-user-active]").checked
        }
      });
      await loadAdmin();
    } catch (error) {
      window.alert(error.message);
    } finally {
      button.disabled = false;
    }
  });

  bootstrap();
})();
