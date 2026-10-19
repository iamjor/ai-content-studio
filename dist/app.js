(function () {
  "use strict";

  var session = null;
  var state = null;
  var revision = 0;
  var saveQueue = Promise.resolve();
  var saveFailed = false;
  var editIndex = -1;
  var characterIndex = -1;
  var projectIndex = -1;
  var promptIndex = -1;
  var editingShots = [];
  var expiryTimer = null;
  var toolRecords = [];
  var statuses = [
    "Script draft", "60s script ready", "References approved",
    "Assets generated", "Editing", "Ready for review", "Approved", "Published"
  ];

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character];
    });
  }

  function safeLink(value) {
    try {
      var url = new URL(value);
      return url.protocol === "https:" ? url.href : "";
    } catch (error) {
      return "";
    }
  }

  function setStatus(element, message, kind) {
    element.textContent = message || "";
    element.classList.toggle("error", kind === "error");
    element.classList.toggle("success", kind === "success");
  }

  async function api(path, options) {
    var requestOptions = Object.assign({}, options || {});
    requestOptions.headers = Object.assign({}, requestOptions.headers || {});
    if (requestOptions.body && typeof requestOptions.body !== "string" && !(requestOptions.body instanceof Blob)) {
      requestOptions.headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(requestOptions.body);
    }
    if (session && requestOptions.method && requestOptions.method !== "GET") {
      requestOptions.headers["X-CSRF-Token"] = session.csrfToken;
    }
    var response = await fetch(path, requestOptions);
    var payload = await response.json().catch(function () { return {}; });
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

  function defaultProject() {
    return {
      id: "sample-series", title: "Sample series", genre: "AI microdrama",
      description: "A fictional starter project. Replace or edit it for your own story.",
      stage: "Planning", archived: false, episodes: structuredClone(seed.episodes),
      characters: structuredClone(seed.characters), gates: structuredClone(seed.gates),
      bible: {}, prompts: []
    };
  }

  /** Add v0.2 planning fields while retaining every legacy value and identifier. */
  function normalizeProject(project) {
    project.episodes = Array.isArray(project.episodes) ? project.episodes : [];
    project.characters = Array.isArray(project.characters) ? project.characters : [];
    project.gates = Array.isArray(project.gates) ? project.gates : [];
    project.prompts = Array.isArray(project.prompts) ? project.prompts : [];
    project.bible = project.bible && typeof project.bible === "object" ? project.bible : {};
    ["logline", "premise", "seasonArc", "worldRules", "toneStyle", "audience", "language", "aspectRatio", "productionConstraints"].forEach(function (field) {
      if (typeof project.bible[field] !== "string") { project.bible[field] = ""; }
    });
    project.archived = Boolean(project.archived);
    project.episodes.forEach(function (episode) {
      episode.archived = Boolean(episode.archived);
      episode.synopsis = typeof episode.synopsis === "string" ? episode.synopsis : "";
      episode.beats = typeof episode.beats === "string" ? episode.beats : "";
      episode.shots = Array.isArray(episode.shots) ? episode.shots : [];
    });
    project.characters.forEach(function (character) {
      character.id = character.id || "c-" + crypto.randomUUID();
      character.archived = Boolean(character.archived);
      character.referenceRequirements = typeof character.referenceRequirements === "string" ? character.referenceRequirements : "";
      character.continuity = character.continuity && typeof character.continuity === "object" ? character.continuity : {};
      ["mustKeep", "mustAvoid", "wardrobeVariants", "voice"].forEach(function (field) {
        if (typeof character.continuity[field] !== "string") { character.continuity[field] = ""; }
      });
    });
  }

  function migrateWorkspace(value) {
    if (value && Array.isArray(value.projects)) {
      value.projects.forEach(normalizeProject);
      if (!value.projects.some(function (project) { return project.id === value.activeId; })) {
        value.activeId = value.projects.length ? value.projects[0].id : "";
      }
      return value;
    }
    if (value && Array.isArray(value.episodes)) {
      var imported = Object.assign(defaultProject(), {
        id: "imported-series", title: "Imported series", episodes: value.episodes,
        characters: value.characters || [], gates: value.gates || []
      });
      normalizeProject(imported);
      return {projects: [imported], activeId: imported.id};
    }
    return {projects: [defaultProject()], activeId: "sample-series"};
  }

  async function applyTheme(theme, persist) {
    var selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    document.querySelector('meta[name="theme-color"]').content = selected === "dark" ? "#07111f" : "#eef8ff";
    document.querySelectorAll(".theme-glyph").forEach(function (glyph) { glyph.textContent = selected === "dark" ? "☀" : "☾"; });
    document.querySelectorAll("#themeToggle,#loginThemeToggle").forEach(function (button) {
      var label = selected === "dark" ? "Use light theme" : "Use dark theme";
      button.setAttribute("aria-label", label);
      button.title = label;
    });
    if (!session) {
      try { localStorage.setItem("aics_public_theme", selected); } catch (error) { return; }
    } else if (persist) {
      try {
        session.user = (await api("/api/account", {method: "PUT", body: {theme: selected}})).user;
      } catch (error) { setStatus(byId("profileStatus"), error.message, "error"); }
    }
  }

  function toggleTheme() {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", Boolean(session));
  }

  function updateFooter(payload) {
    byId("footerAppName").textContent = payload.appName || "AI Content Studio";
    byId("footerVersion").textContent = payload.version ? "v" + payload.version : "";
    byId("footerYear").textContent = String(new Date().getFullYear());
  }

  function scheduleExpiry() {
    if (expiryTimer) { window.clearTimeout(expiryTimer); }
    if (!session) { return; }
    var delay = Math.max(0, session.expiresAt * 1000 - Date.now());
    expiryTimer = window.setTimeout(function () {
      if (session && session.expiresAt * 1000 > Date.now()) { scheduleExpiry(); }
      else { showSignedOut("Your session expired. Sign in again."); }
    }, Math.min(delay, 2147483647));
  }

  /** Hide the neutral startup status after the destination view is ready. */
  function dismissBootstrap() {
    byId("bootstrapView").setAttribute("aria-busy", "false");
    byId("bootstrapView").classList.add("hidden");
  }

  function showSignedOut(message) {
    session = null;
    state = null;
    revision = 0;
    saveFailed = false;
    dismissBootstrap();
    byId("appView").classList.add("hidden");
    byId("authView").classList.remove("hidden");
    byId("loginPassword").value = "";
    setStatus(byId("loginStatus"), message || "", message ? "error" : "");
    byId("registrationPrompt").classList.toggle("hidden", !byId("registrationPrompt").dataset.enabled);
    byId("registerForm").classList.add("hidden");
    byId("loginForm").classList.remove("hidden");
    byId("loginUsername").focus();
  }

  function populateAccount() {
    byId("sideUserName").textContent = session.user.displayName;
    byId("sideUserRole").textContent = session.user.role === "admin" ? "Administrator" : "Private workspace";
    byId("accountUsername").value = session.user.username;
    byId("accountDisplayName").value = session.user.displayName;
    byId("adminNav").classList.toggle("hidden", session.user.role !== "admin");
    byId("toolAdminActions").classList.toggle("hidden", session.user.role !== "admin");
  }

  function renderIntegrations(items) {
    byId("integrationList").innerHTML = items.length ? items.map(function (item) {
      var created = new Date(item.createdAt * 1000).toLocaleString();
      var used = item.lastUsedAt ? new Date(item.lastUsedAt * 1000).toLocaleString() : "Not used yet";
      return '<article class="gate-row" data-integration-id="' + item.id + '"><div><strong>' +
        escapeHtml(item.clientName) + '</strong><p class="muted">Scopes: ' +
        escapeHtml(item.scopes.join(", ")) + '<br>Created: ' + escapeHtml(created) +
        '<br>Last used: ' + escapeHtml(used) + '</p></div><button class="btn danger" ' +
        'data-revoke-integration type="button">Revoke</button></article>';
    }).join("") : '<div class="card empty"><h3>No connected integrations</h3><p>Clients you authorize through OAuth will appear here.</p></div>';
  }

  async function loadIntegrations() {
    if (!session) { return; }
    try {
      renderIntegrations((await api("/api/account/integrations")).integrations);
    } catch (error) {
      setStatus(byId("integrationStatus"), error.message, "error");
    }
  }

  async function copyMcpEndpoint() {
    try {
      await navigator.clipboard.writeText(window.location.origin + "/mcp");
      setStatus(byId("integrationStatus"), "MCP endpoint copied.", "success");
    } catch (error) {
      setStatus(byId("integrationStatus"), "Copy failed. Use " + window.location.origin + "/mcp", "error");
    }
  }

  async function loadWorkspace() {
    var loaded = await api("/api/workspace");
    revision = loaded.revision;
    state = loaded.data ? migrateWorkspace(loaded.data) : migrateWorkspace(null);
    (loaded.imageCharacterIds || []).forEach(function (id) {
      state.projects.forEach(function (project) {
        project.characters.forEach(function (character) {
          if (character.id === id) { character.hasImage = true; }
        });
      });
    });
    saveQueue = Promise.resolve();
    saveFailed = false;
    if (!loaded.data) { persist(); }
    else { byId("syncStatus").textContent = "Saved to your private workspace"; }
    render();
  }

  async function showAuthenticated(payload, focusDestination) {
    session = payload;
    applyTheme(session.user.theme, false);
    populateAccount();
    scheduleExpiry();
    await Promise.all([loadWorkspace(), loadTools(), loadIntegrations()]);
    byId("authView").classList.add("hidden");
    dismissBootstrap();
    byId("appView").classList.remove("hidden");
    goTo("overview", focusDestination);
  }

  function activeProject() {
    if (!state || !state.projects.length) { return null; }
    return state.projects.find(function (project) { return project.id === state.activeId; }) ||
      state.projects.find(function (project) { return !project.archived; }) || state.projects[0];
  }

  function persist() {
    if (saveFailed || !session) { return Promise.resolve(); }
    var snapshot = structuredClone(state);
    snapshot.projects.forEach(function (project) {
      project.characters.forEach(function (character) { delete character.hasImage; });
    });
    byId("syncStatus").textContent = "Saving…";
    saveQueue = saveQueue.then(function () {
      return api("/api/workspace", {method: "PUT", body: {revision: revision, data: snapshot}});
    }).then(function (result) {
      revision = result.revision;
      byId("syncStatus").textContent = "Saved to your private workspace";
    }).catch(function (error) {
      saveFailed = true;
      byId("syncStatus").textContent = "Save failed. Export a backup, then reload.";
      window.alert("Your changes could not be saved: " + error.message);
      throw error;
    });
    return saveQueue;
  }

  function setSidebar(open) {
    byId("appView").querySelector(".shell").classList.toggle("sidebar-closed", !open);
    byId("navToggle").setAttribute("aria-expanded", String(open));
    byId("navToggle").setAttribute("aria-label", open ? "Close sidebar" : "Open sidebar");
    byId("navToggleText").textContent = open ? "Close sidebar" : "Open sidebar";
  }

  /** Focus a section label after its source control may have become hidden. */
  function focusSectionHeading(tab) {
    var section = byId(tab);
    var heading = section && byId(section.getAttribute("aria-labelledby"));
    if (!heading) { return; }
    heading.tabIndex = -1;
    heading.focus({preventScroll: true});
  }

  function goTo(tab, focusDestination) {
    document.querySelectorAll(".nav button,.section").forEach(function (element) { element.classList.remove("active"); });
    var navButton = document.querySelector('.nav button[data-tab="' + tab + '"]');
    if (navButton) { navButton.classList.add("active"); }
    if (byId(tab)) { byId(tab).classList.add("active"); }
    if (window.matchMedia("(max-width: 1080px)").matches) { setSidebar(false); }
    if (tab === "admin" && session.user.role === "admin") { loadAdmin(); }
    if (tab === "tools") { loadTools(); }
    render();
    if (focusDestination) {
      window.requestAnimationFrame(function () { focusSectionHeading(tab); });
    }
  }

  function selectedItems(items, filter) {
    return items.filter(function (item) {
      return filter === "all" || (filter === "archived" ? item.archived : !item.archived);
    });
  }

  function actions(kind, index, archived) {
    var primary = '<button class="btn" type="button" data-item-action="open" data-kind="' + kind + '" data-index="' + index + '">' + (kind === "project" ? "Open" : "Edit") + '</button>';
    if (kind === "project") { primary += '<button class="btn" type="button" data-item-action="edit" data-kind="project" data-index="' + index + '">Edit project</button>'; }
    return '<div class="card-actions">' + primary + '<button class="btn" type="button" data-item-action="' + (archived ? "restore" : "archive") + '" data-kind="' + kind + '" data-index="' + index + '">' + (archived ? "Restore" : "Archive") + '</button><button class="btn danger" type="button" data-item-action="delete" data-kind="' + kind + '" data-index="' + index + '">Delete</button></div>';
  }

  /** Open project creation or editing without cloning an existing project. */
  function openProject(index) {
    projectIndex = index;
    var project = index >= 0 ? state.projects[index] : {title: "", genre: "", description: "", stage: "Planning", bible: {}};
    var bible = project.bible || {};
    byId("projectModalTitle").textContent = index >= 0 ? "Edit project" : "Create project";
    byId("pTitle").value = project.title || "";
    byId("pGenre").value = project.genre || "";
    byId("pDescription").value = project.description || "";
    byId("pStage").value = project.stage || "Planning";
    byId("pLogline").value = bible.logline || "";
    byId("pPremise").value = bible.premise || "";
    byId("pSeasonArc").value = bible.seasonArc || "";
    byId("pWorldRules").value = bible.worldRules || "";
    byId("pToneStyle").value = bible.toneStyle || "";
    byId("pAudience").value = bible.audience || "";
    byId("pLanguage").value = bible.language || "";
    byId("pAspectRatio").value = bible.aspectRatio || "";
    byId("pConstraints").value = bible.productionConstraints || "";
    byId("projectDialog").showModal();
    byId("pTitle").focus();
  }

  /** Render temporary shot drafts so Cancel leaves the saved episode unchanged. */
  function renderShots() {
    byId("shotList").innerHTML = editingShots.length ? editingShots.map(function (shot, index) {
      var options = '<option value="">No linked prompt</option>' + activeProject().prompts.map(function (prompt) { return '<option value="' + escapeHtml(prompt.id) + '"' + (shot.promptId === prompt.id ? " selected" : "") + '>' + escapeHtml(prompt.name) + '</option>'; }).join("");
      return '<fieldset class="shot-card" data-shot-index="' + index + '"><legend>Shot ' + (index + 1) + '</legend><div class="shot-actions"><button class="btn" type="button" data-shot-action="up"' + (index === 0 ? " disabled" : "") + '>Up</button><button class="btn" type="button" data-shot-action="down"' + (index === editingShots.length - 1 ? " disabled" : "") + '>Down</button><button class="btn danger" type="button" data-shot-action="remove">Remove</button></div><div class="settings-grid"><label class="field">Time range<input data-shot-field="timeRange" maxlength="40" value="' + escapeHtml(shot.timeRange) + '" placeholder="0:00-0:05"></label><label class="field">Status<select data-shot-field="status"><option' + (shot.status === "Planned" ? " selected" : "") + '>Planned</option><option' + (shot.status === "In progress" ? " selected" : "") + '>In progress</option><option' + (shot.status === "Ready for review" ? " selected" : "") + '>Ready for review</option><option' + (shot.status === "Approved" ? " selected" : "") + '>Approved</option></select></label></div><label class="field">Visual beat<textarea class="textarea-short" data-shot-field="visualBeat">' + escapeHtml(shot.visualBeat) + '</textarea></label><label class="field">Camera / action<textarea class="textarea-short" data-shot-field="cameraAction">' + escapeHtml(shot.cameraAction) + '</textarea></label><label class="field">Dialogue / voiceover<textarea class="textarea-short" data-shot-field="dialogue">' + escapeHtml(shot.dialogue) + '</textarea></label><label class="field">SFX / music notes<textarea class="textarea-short" data-shot-field="audioNotes">' + escapeHtml(shot.audioNotes) + '</textarea></label><label class="field">Linked reusable prompt<select data-shot-field="promptId">' + options + '</select></label><label class="field">Final text-to-image prompt<textarea data-shot-field="imagePrompt">' + escapeHtml(shot.imagePrompt) + '</textarea></label><label class="field">Final image-to-video prompt<textarea data-shot-field="videoPrompt">' + escapeHtml(shot.videoPrompt) + '</textarea></label><label class="field">Reference asset IDs / private links<textarea class="textarea-short" data-shot-field="referenceAssets">' + escapeHtml(shot.referenceAssets) + '</textarea></label><label class="field">Model / settings<textarea class="textarea-short" data-shot-field="modelSettings">' + escapeHtml(shot.modelSettings) + '</textarea></label><label class="field">Output / review link<input data-shot-field="outputLink" maxlength="1000" value="' + escapeHtml(shot.outputLink) + '"></label></fieldset>';
    }).join("") : '<div class="card empty"><h3>No shots yet</h3><p>Add only the shots needed for a practical short-form plan.</p></div>';
  }

  /** Capture visible shot fields before reordering or saving the episode. */
  function collectShots() {
    byId("shotList").querySelectorAll("[data-shot-index]").forEach(function (card) {
      var shot = editingShots[Number(card.dataset.shotIndex)];
      card.querySelectorAll("[data-shot-field]").forEach(function (field) { shot[field.dataset.shotField] = field.value; });
    });
  }

  /** Open one project-scoped reusable prompt for editing. */
  function openPrompt(index) {
    promptIndex = index;
    var prompt = index >= 0 ? activeProject().prompts[index] : {name: "", category: "Style", purpose: "", body: "", modelSettings: ""};
    byId("promptModalTitle").textContent = index >= 0 ? "Edit prompt" : "Add prompt";
    byId("promptName").value = prompt.name;
    byId("promptCategory").value = prompt.category || "Style";
    byId("promptPurpose").value = prompt.purpose || "";
    byId("promptBody").value = prompt.body || "";
    byId("promptSettings").value = prompt.modelSettings || "";
    byId("deletePrompt").classList.toggle("hidden", index < 0);
    byId("promptDialog").showModal();
    byId("promptName").focus();
  }

  function render() {
    if (!state) { return; }
    var activeProjects = state.projects.filter(function (item) { return !item.archived; });
    var project = activeProject();
    byId("projectCount").textContent = String(activeProjects.length);
    byId("episodeCount").textContent = String(activeProjects.reduce(function (sum, item) { return sum + item.episodes.filter(function (entry) { return !entry.archived; }).length; }, 0));
    byId("readyCount").textContent = String(activeProjects.reduce(function (sum, item) { return sum + item.episodes.filter(function (entry) { return !entry.archived && ["Approved", "Published"].includes(entry.status); }).length; }, 0));
    byId("sheetCount").textContent = String(activeProjects.reduce(function (sum, item) { return sum + item.characters.filter(function (entry) { return !entry.archived && entry.state === "Reference approved"; }).length; }, 0));

    function projectCards(filter, home) {
      var entries = selectedItems(state.projects, home ? "active" : filter);
      if (!entries.length) { return '<div class="card empty"><h3>' + (state.projects.length ? "Nothing in this view" : "Your workspace is empty") + '</h3><p>Create a project to start planning a story.</p><button class="btn primary" data-new type="button">+ New project</button></div>'; }
      return entries.map(function (item) {
        var index = state.projects.indexOf(item);
        return '<article class="card projectcard"><div class="kicker">' + escapeHtml(item.genre || "New project") + '</div><h3>' + escapeHtml(item.title) + '</h3><p>' + escapeHtml(item.description || "Your next creative world begins here.") + '</p><span class="badge ' + (item.archived ? "" : "amber") + '">' + (item.archived ? "Archived" : escapeHtml(item.stage || "Planning")) + ' · ' + item.episodes.filter(function (episode) { return !episode.archived; }).length + ' episodes</span>' + actions("project", index, item.archived) + '</article>';
      }).join("");
    }
    byId("homeProjects").innerHTML = projectCards("active", true);
    byId("projectGrid").innerHTML = projectCards(byId("projectFilter").value, false);

    var hasProject = Boolean(project);
    byId("addEpisode").disabled = !hasProject;
    byId("addCharacter").disabled = !hasProject;
    byId("addPrompt").disabled = !hasProject;
    byId("addGate").disabled = !hasProject;
    byId("activeTitle").textContent = hasProject ? project.title : "No project selected";
    byId("activeMeta").textContent = hasProject ? (project.genre || "Untitled format") + " · " + project.episodes.filter(function (item) { return !item.archived; }).length + " active episodes" : "Create a project to add episodes.";
    byId("characterTitle").textContent = hasProject ? project.title : "No project selected";
    byId("promptProjectTitle").textContent = hasProject ? project.title : "No project selected";
    byId("workflowProjectTitle").textContent = hasProject ? project.title : "No project selected";
    if (!project) {
      byId("episodeGrid").innerHTML = '<div class="card empty"><h3>No project yet</h3><p>Create a project before adding episodes.</p></div>';
      byId("characterGrid").innerHTML = '<div class="card empty"><h3>No project yet</h3><p>Create a project before adding characters.</p></div>';
      byId("promptGrid").innerHTML = '<div class="card empty"><h3>No project yet</h3><p>Create a project before saving prompts.</p></div>';
      byId("gateList").innerHTML = '<div class="card empty"><h3>No project yet</h3><p>Create a project before tracking production gates.</p></div>';
      byId("workflowShotSummary").textContent = "Create a project to track shot progress.";
      return;
    }

    var episodes = selectedItems(project.episodes, byId("episodeFilter").value);
    byId("episodeGrid").innerHTML = episodes.length ? episodes.map(function (episode) {
      var index = project.episodes.indexOf(episode);
      var meter = Math.max(9, (statuses.indexOf(episode.status) + 1) * 12);
      return '<article class="card"><div class="kicker">' + escapeHtml(episode.id) + ' · ' + escapeHtml(episode.duration || 60) + ' seconds</div><h3>' + escapeHtml(episode.title) + '</h3><p>' + escapeHtml(episode.hook) + '</p><progress class="meter" max="100" value="' + meter + '">' + meter + '%</progress><span class="badge ' + (episode.archived ? "" : "amber") + '">' + (episode.archived ? "Archived" : escapeHtml(episode.status || "Script draft")) + '</span>' + actions("episode", index, episode.archived) + '</article>';
    }).join("") : '<div class="card empty"><h3>No episodes in this view</h3><p>Add an episode or change the filter.</p></div>';

    var characters = selectedItems(project.characters, byId("characterFilter").value);
    byId("characterGrid").innerHTML = characters.length ? characters.map(function (character) {
      var index = project.characters.indexOf(character);
      var reference = safeLink(character.link);
      var image = character.hasImage ? '<img class="character-thumb" src="/api/characters/' + encodeURIComponent(character.id) + '/image" alt="Reference for ' + escapeHtml(character.name) + '">' : "";
      return '<article class="card">' + image + '<div class="kicker">' + escapeHtml(character.role || "Character") + ' · ' + escapeHtml(character.age || "") + '</div><h3>' + escapeHtml(character.name) + '</h3><p>' + escapeHtml(character.look) + '</p><span class="badge ' + (character.archived ? "" : "amber") + '">' + (character.archived ? "Archived" : escapeHtml(character.state || "Written canon only")) + '</span>' + (reference ? '<p><a href="' + escapeHtml(reference) + '" target="_blank" rel="noopener noreferrer">Reference link</a></p>' : "") + actions("character", index, character.archived) + '</article>';
    }).join("") : '<div class="card empty"><h3>No characters in this view</h3><p>Add a character or change the filter.</p></div>';

    byId("promptGrid").innerHTML = project.prompts.length ? project.prompts.map(function (prompt, index) {
      return '<article class="card prompt-card"><div class="kicker">' + escapeHtml(prompt.category || "Other") + '</div><h3>' + escapeHtml(prompt.name) + '</h3><p>' + escapeHtml(prompt.purpose || "Reusable project prompt") + '</p><pre>' + escapeHtml(prompt.body) + '</pre><p class="muted">Updated ' + escapeHtml(prompt.updatedAt || "Not recorded") + '</p><div class="card-actions"><button class="btn" type="button" data-prompt-action="copy" data-index="' + index + '">Copy</button><button class="btn" type="button" data-prompt-action="edit" data-index="' + index + '">Edit</button></div></article>';
    }).join("") : '<div class="card empty"><h3>No saved prompts</h3><p>Add a reusable style, subject, location, image, video, or negative prompt.</p></div>';

    var shots = project.episodes.reduce(function (all, episode) { return all.concat(episode.shots || []); }, []);
    var approvedShots = shots.filter(function (shot) { return shot.status === "Approved"; }).length;
    byId("workflowShotSummary").textContent = shots.length + " shots planned, " + approvedShots + " approved. Episode status requires an explicit owner selection.";
    byId("gateList").innerHTML = project.gates.length ? project.gates.map(function (gate, index) {
      return '<article class="gate-row"><input aria-label="Gate complete" type="checkbox" data-gate-done="' + index + '"' + (gate.done ? " checked" : "") + '><input aria-label="Gate name" type="text" maxlength="160" data-gate-name="' + index + '" value="' + escapeHtml(gate.name) + '"><button class="btn danger" type="button" data-gate-remove="' + index + '">Remove</button></article>';
    }).join("") : '<div class="card empty"><h3>No production gates</h3><p>Add the manual review decisions this project needs.</p></div>';
  }

  function openEpisode(index) {
    editIndex = index;
    var episode = activeProject().episodes[index];
    byId("modalKicker").textContent = episode.id;
    byId("modalTitle").textContent = episode.title;
    byId("eTitle").value = episode.title;
    byId("hook").value = episode.hook || "";
    byId("episodeSynopsis").value = episode.synopsis || "";
    byId("episodeBeats").value = episode.beats || "";
    byId("status").value = episode.status || "Script draft";
    byId("duration").value = episode.duration || 60;
    byId("script").value = episode.script || "";
    byId("assetLink").value = episode.assetLink || "";
    editingShots = structuredClone(episode.shots || []);
    renderShots();
    byId("archiveEpisode").textContent = episode.archived ? "Restore" : "Archive";
    byId("editor").showModal();
  }

  function openCharacter(index) {
    characterIndex = index;
    var character = index >= 0 ? activeProject().characters[index] : {id: "c-" + crypto.randomUUID(), name: "", role: "", age: "", look: "", state: "Written canon only", link: "", archived: false};
    byId("characterModalTitle").textContent = index >= 0 ? "Edit character" : "Add character";
    byId("cName").value = character.name;
    byId("cRole").value = character.role;
    byId("cAge").value = character.age;
    byId("cLook").value = character.look;
    byId("cReferenceRequirements").value = character.referenceRequirements || "";
    byId("cMustKeep").value = (character.continuity || {}).mustKeep || "";
    byId("cMustAvoid").value = (character.continuity || {}).mustAvoid || "";
    byId("cWardrobe").value = (character.continuity || {}).wardrobeVariants || "";
    byId("cVoice").value = (character.continuity || {}).voice || "";
    byId("cState").value = character.state;
    byId("cLink").value = character.link || "";
    byId("cImage").value = "";
    byId("characterImageActions").classList.toggle("hidden", !character.hasImage);
    byId("viewCharacterImage").href = character.hasImage ? "/api/characters/" + encodeURIComponent(character.id) + "/image" : "";
    byId("deleteCharacter").classList.toggle("hidden", index < 0);
    byId("archiveCharacter").classList.toggle("hidden", index < 0);
    byId("archiveCharacter").textContent = character.archived ? "Restore" : "Archive";
    byId("characterDialog").showModal();
  }

  function renderUsers(users) {
    var filter = byId("userFilter").value;
    users = users.filter(function (user) { return filter === "all" || (filter === "archived" ? user.archived : !user.archived); });
    byId("userList").innerHTML = users.length ? users.map(function (user) {
      return '<article class="user-row" data-user-row="' + user.id + '"><div class="user-meta"><strong>' + escapeHtml(user.displayName) + '</strong><span>@' + escapeHtml(user.username) + ' · ' + (user.archived ? "Archived" : user.active ? "Active" : "Disabled") + '</span></div><label class="field">Role<select data-user-role><option value="user"' + (user.role === "user" ? " selected" : "") + '>User</option><option value="admin"' + (user.role === "admin" ? " selected" : "") + '>Admin</option></select></label><div class="card-actions"><button class="btn" data-user-action="role" type="button">Save role</button>' + (user.archived ? '<button class="btn" data-user-action="restore" type="button">Restore</button>' : (user.active ? '<button class="btn" data-user-action="disable" type="button">Disable</button><button class="btn" data-user-action="archive" type="button">Archive</button>' : '<button class="btn" data-user-action="restore" type="button">Restore</button><button class="btn" data-user-action="archive" type="button">Archive</button>')) + '<button class="btn danger" data-user-action="delete" type="button">Delete</button></div></article>';
    }).join("") : '<div class="card empty"><h3>No users in this view</h3></div>';
  }

  async function loadAdmin() {
    if (!session || session.user.role !== "admin") { return; }
    try {
      var results = await Promise.all([api("/api/admin/users"), api("/api/admin/settings")]);
      byId("userList").dataset.users = JSON.stringify(results[0].users);
      renderUsers(results[0].users);
      byId("registrationEnabled").checked = results[1].registrationEnabled;
    } catch (error) { setStatus(byId("adminSettingsStatus"), error.message, "error"); }
  }

  function renderTools() {
    var filter = session && session.user.role === "admin" ? byId("toolFilter").value : "active";
    var tools = selectedItems(toolRecords, filter);
    byId("toolGrid").innerHTML = tools.length ? tools.map(function (tool) {
      return '<article class="card catalog-card" data-tool-id="' + tool.id + '"><div><div class="kicker">' + escapeHtml(tool.category) + (tool.archived ? " · Archived" : "") + '</div><h3>' + escapeHtml(tool.name) + '</h3><p>' + escapeHtml(tool.purpose) + '</p>' + (tool.notes ? '<p class="muted">' + escapeHtml(tool.notes) + '</p>' : "") + '<a href="' + escapeHtml(safeLink(tool.url)) + '" target="_blank" rel="noopener noreferrer">Open official site</a></div>' + (session.user.role === "admin" ? '<div class="card-actions"><button class="btn" data-tool-action="edit" type="button">Edit</button><button class="btn" data-tool-action="' + (tool.archived ? "restore" : "archive") + '" type="button">' + (tool.archived ? "Restore" : "Archive") + '</button><button class="btn danger" data-tool-action="delete" type="button">Delete</button></div>' : "") + '</article>';
    }).join("") : '<div class="card empty"><h3>No tools in this view</h3><p>An administrator can add a shared production tool.</p></div>';
  }

  async function loadTools() {
    if (!session) { return; }
    try { toolRecords = (await api("/api/tools")).tools; renderTools(); }
    catch (error) { byId("toolGrid").innerHTML = '<div class="notice">' + escapeHtml(error.message) + '</div>'; }
  }

  /** Reset tool dialog state so values and errors never leak between opens. */
  function clearToolForm() {
    byId("toolForm").reset();
    byId("toolId").value = "";
    byId("toolFormTitle").textContent = "Add tool";
    setStatus(byId("toolStatus"), "", "");
  }

  /** Open the shared tool editor for a new record or one selected record. */
  function openToolDialog(tool) {
    clearToolForm();
    if (tool) {
      byId("toolId").value = tool.id;
      byId("toolName").value = tool.name;
      byId("toolCategory").value = tool.category;
      byId("toolUrl").value = tool.url;
      byId("toolPurpose").value = tool.purpose;
      byId("toolNotes").value = tool.notes;
      byId("toolFormTitle").textContent = "Edit tool";
    }
    byId("toolDialog").showModal();
    byId("toolName").focus();
  }

  async function bootstrap() {
    byId("footerYear").textContent = String(new Date().getFullYear());
    var payload;
    try {
      payload = await api("/api/session");
      updateFooter(payload);
      byId("registrationPrompt").dataset.enabled = payload.registrationEnabled ? "true" : "";
      if (payload.authenticated) { await showAuthenticated(payload, false); return; }
    } catch (error) {
      updateFooter({appName: "AI Content Studio", version: ""});
      var fallbackTheme = "dark";
      try { fallbackTheme = localStorage.getItem("aics_public_theme") || "dark"; } catch (storageError) { fallbackTheme = "dark"; }
      applyTheme(fallbackTheme, false);
      showSignedOut("The studio server is unavailable. Try again shortly.");
      return;
    }
    var publicTheme = "dark";
    try { publicTheme = localStorage.getItem("aics_public_theme") || "dark"; } catch (error) { publicTheme = "dark"; }
    applyTheme(publicTheme, false);
    showSignedOut("");
  }

  byId("loginThemeToggle").addEventListener("click", toggleTheme);
  byId("themeToggle").addEventListener("click", toggleTheme);
  byId("showRegister").addEventListener("click", function () { byId("loginForm").classList.add("hidden"); byId("registrationPrompt").classList.add("hidden"); byId("registerForm").classList.remove("hidden"); byId("registerName").focus(); });
  byId("hideRegister").addEventListener("click", function () { byId("registerForm").classList.add("hidden"); byId("loginForm").classList.remove("hidden"); byId("registrationPrompt").classList.remove("hidden"); byId("loginUsername").focus(); });
  byId("loginForm").addEventListener("submit", async function (event) { event.preventDefault(); setStatus(byId("loginStatus"), "Signing in…", ""); try { var payload = await api("/api/login", {method: "POST", body: {username: byId("loginUsername").value.trim(), password: byId("loginPassword").value}}); updateFooter(payload); await showAuthenticated(payload, true); byId("loginForm").reset(); } catch (error) { setStatus(byId("loginStatus"), error.message, "error"); } });
  byId("registerForm").addEventListener("submit", async function (event) { event.preventDefault(); setStatus(byId("registerStatus"), "Creating your workspace…", ""); try { var payload = await api("/api/register", {method: "POST", body: {displayName: byId("registerName").value.trim(), username: byId("registerUsername").value.trim(), password: byId("registerPassword").value}}); updateFooter(payload); await showAuthenticated(payload, true); byId("registerForm").reset(); } catch (error) { setStatus(byId("registerStatus"), error.message, "error"); } });
  byId("logout").addEventListener("click", async function () { try { await api("/api/logout", {method: "POST", body: {}}); } catch (error) { if (error.status !== 401) { window.alert(error.message); } } showSignedOut("You have been signed out."); });

  setSidebar(!window.matchMedia("(max-width: 1080px)").matches);
  byId("navToggle").addEventListener("click", function () { setSidebar(byId("navToggle").getAttribute("aria-expanded") !== "true"); });
  document.querySelectorAll(".nav button").forEach(function (button) { button.addEventListener("click", function () { goTo(button.dataset.tab, true); }); });
  ["projectFilter", "episodeFilter", "characterFilter"].forEach(function (id) { byId(id).addEventListener("change", render); });
  byId("toolFilter").addEventListener("change", renderTools);
  byId("userFilter").addEventListener("change", function () { var users = JSON.parse(byId("userList").dataset.users || "[]"); renderUsers(users); });

  document.querySelectorAll("dialog [data-cancel]").forEach(function (button) { button.addEventListener("click", function () { button.closest("dialog").close("cancel"); }); });
  document.body.addEventListener("click", async function (event) {
    var goButton = event.target.closest("[data-go]");
    if (goButton) { goTo(goButton.dataset.go, true); return; }
    if (event.target.closest("[data-open-bible]") && activeProject()) { openProject(state.projects.indexOf(activeProject())); return; }
    if (event.target.closest("[data-new]")) { openProject(-1); return; }
    var button = event.target.closest("[data-item-action]");
    if (!button) { return; }
    var project = activeProject();
    var list = button.dataset.kind === "project" ? state.projects : button.dataset.kind === "episode" ? project.episodes : project.characters;
    var item = list[Number(button.dataset.index)];
    if (button.dataset.itemAction === "edit" && button.dataset.kind === "project") { openProject(Number(button.dataset.index)); return; }
    if (button.dataset.itemAction === "open") {
      if (button.dataset.kind === "project") { state.activeId = item.id; persist(); goTo("episodes", true); }
      else if (button.dataset.kind === "episode") { openEpisode(Number(button.dataset.index)); }
      else { openCharacter(Number(button.dataset.index)); }
      return;
    }
    if (button.dataset.itemAction === "delete") {
      var warning = button.dataset.kind === "project" ? "Permanently delete this project, all its episodes, characters, and uploaded character images?" : "Permanently delete this " + button.dataset.kind + " and its uploaded image, if any?";
      if (!window.confirm(warning)) { return; }
      list.splice(Number(button.dataset.index), 1);
      if (button.dataset.kind === "project") { state.activeId = state.projects.length ? state.projects[0].id : ""; }
    } else { item.archived = button.dataset.itemAction === "archive"; }
    await persist();
    render();
  });

  byId("newProject").addEventListener("click", function () { openProject(-1); });
  byId("projectForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    var existing = projectIndex >= 0 ? state.projects[projectIndex] : null;
    var project = existing || {id: "p-" + crypto.randomUUID(), archived: false, episodes: [], characters: [], gates: [], prompts: []};
    project.title = byId("pTitle").value.trim();
    project.genre = byId("pGenre").value.trim();
    project.description = byId("pDescription").value.trim();
    project.stage = byId("pStage").value.trim() || "Planning";
    project.bible = {logline: byId("pLogline").value.trim(), premise: byId("pPremise").value.trim(), seasonArc: byId("pSeasonArc").value.trim(), worldRules: byId("pWorldRules").value.trim(), toneStyle: byId("pToneStyle").value.trim(), audience: byId("pAudience").value.trim(), language: byId("pLanguage").value.trim(), aspectRatio: byId("pAspectRatio").value.trim(), productionConstraints: byId("pConstraints").value.trim()};
    if (!existing) { state.projects.push(project); state.activeId = project.id; }
    await persist();
    render();
    byId("projectDialog").close();
    goTo(projectIndex >= 0 ? "projects" : "episodes", true);
  });
  byId("addEpisode").addEventListener("click", function () { var project = activeProject(); if (!project) { return; } var id = "EP" + String(project.episodes.length + 1).padStart(2, "0"); project.episodes.push({id: id, title: "Untitled episode", hook: "", synopsis: "", beats: "", shots: [], status: "Script draft", duration: 60, script: "", assetLink: "", archived: false}); persist(); render(); openEpisode(project.episodes.length - 1); });
  byId("editForm").addEventListener("submit", function () {
    var episode = activeProject().episodes[editIndex];
    if (!episode) { return; }
    collectShots();
    episode.title = byId("eTitle").value.trim();
    episode.hook = byId("hook").value.trim();
    episode.synopsis = byId("episodeSynopsis").value.trim();
    episode.beats = byId("episodeBeats").value.trim();
    episode.shots = structuredClone(editingShots);
    episode.status = byId("status").value;
    episode.duration = Number(byId("duration").value) || 60;
    episode.script = byId("script").value;
    episode.assetLink = byId("assetLink").value.trim();
    persist();
    render();
  });
  byId("archiveEpisode").addEventListener("click", function () { var episode = activeProject().episodes[editIndex]; episode.archived = !episode.archived; persist(); render(); byId("editor").close(); });
  byId("deleteEpisode").addEventListener("click", function () { if (window.confirm("Permanently delete this episode?")) { activeProject().episodes.splice(editIndex, 1); persist(); render(); byId("editor").close(); } });
  byId("addShot").addEventListener("click", function () {
    collectShots();
    editingShots.push({id: "shot-" + crypto.randomUUID(), timeRange: "", visualBeat: "", cameraAction: "", dialogue: "", audioNotes: "", promptId: "", imagePrompt: "", videoPrompt: "", referenceAssets: "", modelSettings: "", outputLink: "", status: "Planned"});
    renderShots();
  });
  byId("shotList").addEventListener("click", function (event) {
    var button = event.target.closest("[data-shot-action]");
    if (!button) { return; }
    collectShots();
    var index = Number(button.closest("[data-shot-index]").dataset.shotIndex);
    if (button.dataset.shotAction === "remove") { editingShots.splice(index, 1); }
    if (button.dataset.shotAction === "up" && index > 0) { editingShots.splice(index - 1, 0, editingShots.splice(index, 1)[0]); }
    if (button.dataset.shotAction === "down" && index < editingShots.length - 1) { editingShots.splice(index + 1, 0, editingShots.splice(index, 1)[0]); }
    renderShots();
  });

  byId("addCharacter").addEventListener("click", function () { if (activeProject()) { openCharacter(-1); } });
  byId("characterForm").addEventListener("submit", async function (event) {
    event.preventDefault();
    var existing = characterIndex >= 0 ? activeProject().characters[characterIndex] : null;
    var character = {id: existing ? existing.id : "c-" + crypto.randomUUID(), name: byId("cName").value.trim(), role: byId("cRole").value.trim(), age: byId("cAge").value.trim(), look: byId("cLook").value.trim(), referenceRequirements: byId("cReferenceRequirements").value.trim(), continuity: {mustKeep: byId("cMustKeep").value.trim(), mustAvoid: byId("cMustAvoid").value.trim(), wardrobeVariants: byId("cWardrobe").value.trim(), voice: byId("cVoice").value.trim()}, state: byId("cState").value, link: byId("cLink").value.trim(), archived: existing ? existing.archived : false, hasImage: existing ? existing.hasImage : false};
    if (characterIndex < 0) { activeProject().characters.push(character); characterIndex = activeProject().characters.length - 1; }
    else { activeProject().characters[characterIndex] = character; }
    await persist();
    var file = byId("cImage").files[0];
    try {
      if (file) { await api("/api/characters/" + encodeURIComponent(character.id) + "/image", {method: "PUT", body: file}); character.hasImage = true; }
      render();
      byId("characterDialog").close();
    } catch (error) {
      window.alert(error.message);
    }
  });
  byId("archiveCharacter").addEventListener("click", function () { var character = activeProject().characters[characterIndex]; character.archived = !character.archived; persist(); render(); byId("characterDialog").close(); });
  byId("deleteCharacter").addEventListener("click", function () { if (window.confirm("Permanently delete this character and its uploaded reference image?")) { activeProject().characters.splice(characterIndex, 1); persist(); render(); byId("characterDialog").close(); } });
  byId("removeCharacterImage").addEventListener("click", async function () { var character = activeProject().characters[characterIndex]; if (!window.confirm("Remove this private reference image?")) { return; } await api("/api/characters/" + encodeURIComponent(character.id) + "/image", {method: "DELETE"}); character.hasImage = false; byId("characterImageActions").classList.add("hidden"); render(); });

  byId("addPrompt").addEventListener("click", function () { if (activeProject()) { openPrompt(-1); } });
  byId("promptForm").addEventListener("submit", function (event) {
    event.preventDefault();
    var existing = promptIndex >= 0 ? activeProject().prompts[promptIndex] : null;
    var prompt = {id: existing ? existing.id : "prompt-" + crypto.randomUUID(), name: byId("promptName").value.trim(), category: byId("promptCategory").value, purpose: byId("promptPurpose").value.trim(), body: byId("promptBody").value, modelSettings: byId("promptSettings").value.trim(), updatedAt: new Date().toISOString()};
    if (promptIndex < 0) { activeProject().prompts.push(prompt); }
    else { activeProject().prompts[promptIndex] = prompt; }
    persist();
    render();
    byId("promptDialog").close();
  });
  byId("deletePrompt").addEventListener("click", function () {
    if (promptIndex >= 0 && window.confirm("Delete this reusable prompt? Existing shot prompt snapshots will remain unchanged.")) {
      activeProject().prompts.splice(promptIndex, 1);
      persist();
      render();
      byId("promptDialog").close();
    }
  });
  byId("promptGrid").addEventListener("click", async function (event) {
    var button = event.target.closest("[data-prompt-action]");
    if (!button) { return; }
    var prompt = activeProject().prompts[Number(button.dataset.index)];
    if (button.dataset.promptAction === "edit") { openPrompt(Number(button.dataset.index)); return; }
    try {
      await navigator.clipboard.writeText(prompt.body);
      button.textContent = "Copied";
      window.setTimeout(function () { button.textContent = "Copy"; }, 1200);
    } catch (error) { window.alert("Copy was blocked by this browser. Open Edit prompt to select the text."); }
  });

  byId("addGate").addEventListener("click", function () {
    if (!activeProject()) { return; }
    var name = window.prompt("Name this manual production gate:");
    if (!name || !name.trim()) { return; }
    activeProject().gates.push({name: name.trim().slice(0, 160), done: false});
    persist();
    render();
  });
  byId("gateList").addEventListener("change", function (event) {
    if (event.target.matches("[data-gate-done]")) { activeProject().gates[Number(event.target.dataset.gateDone)].done = event.target.checked; }
    if (event.target.matches("[data-gate-name]")) {
      var value = event.target.value.trim();
      if (!value) { render(); return; }
      activeProject().gates[Number(event.target.dataset.gateName)].name = value;
    }
    persist();
    render();
  });
  byId("gateList").addEventListener("click", function (event) {
    var button = event.target.closest("[data-gate-remove]");
    if (!button || !window.confirm("Remove this project gate?")) { return; }
    activeProject().gates.splice(Number(button.dataset.gateRemove), 1);
    persist();
    render();
  });

  byId("export").addEventListener("click", function () { window.alert("This JSON export contains text records only. Uploaded images are not included. Back up the persistent data volume for a complete image-inclusive backup."); var clean = structuredClone(state); clean.projects.forEach(function (project) { project.characters.forEach(function (character) { delete character.hasImage; }); }); var anchor = document.createElement("a"); var url = URL.createObjectURL(new Blob([JSON.stringify(clean, null, 2)], {type: "application/json"})); anchor.href = url; anchor.download = "ai-content-studio-text-backup.json"; anchor.click(); window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000); });
  byId("import").addEventListener("click", function () { byId("file").click(); });
  byId("file").addEventListener("change", async function (event) { var file = event.target.files && event.target.files[0]; if (!file) { return; } try { var parsed = JSON.parse(await file.text()); if (!parsed || (!Array.isArray(parsed.projects) && !Array.isArray(parsed.episodes))) { throw new Error("Invalid"); } var imported = migrateWorkspace(parsed); if (window.confirm("Replace every text record in your private workspace? Uploaded images are not restored by JSON import.")) { state = imported; await persist(); render(); goTo("overview", true); } } catch (error) { window.alert("This is not a valid AI Content Studio text backup."); } event.target.value = ""; });

  byId("profileForm").addEventListener("submit", async function (event) { event.preventDefault(); try { session.user = (await api("/api/account", {method: "PUT", body: {displayName: byId("accountDisplayName").value.trim()}})).user; populateAccount(); setStatus(byId("profileStatus"), "Profile saved.", "success"); } catch (error) { setStatus(byId("profileStatus"), error.message, "error"); } });
  byId("passwordForm").addEventListener("submit", async function (event) { event.preventDefault(); try { var result = await api("/api/account", {method: "PUT", body: {currentPassword: byId("currentPassword").value, newPassword: byId("newPassword").value}}); byId("passwordForm").reset(); showSignedOut(result.message || "Password changed. Sign in again."); } catch (error) { setStatus(byId("passwordStatus"), error.message, "error"); } });
  byId("copyMcpEndpoint").addEventListener("click", copyMcpEndpoint);
  byId("integrationList").addEventListener("click", async function (event) {
    var button = event.target.closest("[data-revoke-integration]");
    if (!button) { return; }
    var row = button.closest("[data-integration-id]");
    if (!window.confirm("Revoke this integration and invalidate all of its tokens?")) { return; }
    try {
      await api("/api/account/integrations/" + row.dataset.integrationId, {method: "DELETE"});
      setStatus(byId("integrationStatus"), "Integration revoked.", "success");
      await loadIntegrations();
    } catch (error) {
      setStatus(byId("integrationStatus"), error.message, "error");
    }
  });
  byId("registrationSettingsForm").addEventListener("submit", async function (event) { event.preventDefault(); try { var result = await api("/api/admin/settings", {method: "PUT", body: {registrationEnabled: byId("registrationEnabled").checked}}); byId("registrationPrompt").dataset.enabled = result.registrationEnabled ? "true" : ""; setStatus(byId("adminSettingsStatus"), "Registration setting saved.", "success"); } catch (error) { setStatus(byId("adminSettingsStatus"), error.message, "error"); } });
  byId("userList").addEventListener("click", async function (event) { var button = event.target.closest("[data-user-action]"); if (!button) { return; } var row = button.closest("[data-user-row]"); var action = button.dataset.userAction; if (action === "delete" && !window.confirm("Permanently delete this account, its workspace, and all uploaded assets? This cannot be undone.")) { return; } if (["disable", "archive"].includes(action) && !window.confirm((action === "disable" ? "Disable sign-in" : "Archive this account") + " while retaining its workspace and uploads?")) { return; } try { if (action === "delete") { await api("/api/admin/users/" + row.dataset.userRow, {method: "DELETE"}); } else { await api("/api/admin/users/" + row.dataset.userRow, {method: "PUT", body: {action: action, role: row.querySelector("[data-user-role]").value}}); } await loadAdmin(); } catch (error) { window.alert(error.message); } });

  byId("addTool").addEventListener("click", function () { openToolDialog(null); });
  byId("toolDialog").addEventListener("close", clearToolForm);
  byId("toolForm").addEventListener("submit", async function (event) { event.preventDefault(); var id = byId("toolId").value; var body = {action: "edit", name: byId("toolName").value.trim(), category: byId("toolCategory").value.trim(), url: byId("toolUrl").value.trim(), purpose: byId("toolPurpose").value.trim(), notes: byId("toolNotes").value.trim()}; try { await api(id ? "/api/admin/tools/" + id : "/api/admin/tools", {method: id ? "PUT" : "POST", body: body}); await loadTools(); byId("toolDialog").close(); } catch (error) { setStatus(byId("toolStatus"), error.message, "error"); } });
  byId("toolGrid").addEventListener("click", async function (event) { var button = event.target.closest("[data-tool-action]"); if (!button) { return; } var card = button.closest("[data-tool-id]"); var tool = toolRecords.find(function (item) { return String(item.id) === card.dataset.toolId; }); var action = button.dataset.toolAction; if (action === "edit") { openToolDialog(tool); return; } if (action === "delete" && !window.confirm("Permanently delete this shared tool?")) { return; } try { if (action === "delete") { await api("/api/admin/tools/" + tool.id, {method: "DELETE"}); } else { await api("/api/admin/tools/" + tool.id, {method: "PUT", body: {action: action}}); } await loadTools(); } catch (error) { window.alert(error.message); } });

  bootstrap();
})();
