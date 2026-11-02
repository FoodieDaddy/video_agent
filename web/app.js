/* AI Film Studio — vanilla console.
 *
 * No build step on purpose: this file is served as-is by the API process, so a
 * fresh checkout only needs `uvicorn app.main:app` to get a usable studio.
 *
 * Every long action is a queued task. Single stages are requested with
 * `?wait=true`; the full workflow is streamed through the SSE endpoint so the
 * log shows each agent as it runs.
 */
(() => {
  "use strict";

  const API = "/api/v1";
  const STORAGE_USER = "afs.user";
  const STORAGE_ROLE = "afs.role";
  const STORAGE_PROJECT = "afs.project";
  const TERMINAL = ["succeeded", "failed", "cancelled"];

  const state = {
    user: localStorage.getItem(STORAGE_USER) || "user_demo",
    role: localStorage.getItem(STORAGE_ROLE) || "admin",
    projectId: localStorage.getItem(STORAGE_PROJECT) || "",
    meta: null,
    tab: "story",
    renderToken: 0,
    controller: null,
  };

  const STATUS_TONE = {
    completed: "ok",
    succeeded: "ok",
    approved: "ok",
    generated: "ok",
    ready: "ok",
    exported: "ok",
    running: "warn",
    rendering: "warn",
    awaiting_review: "warn",
    pending: "warn",
    queued: "warn",
    created: "warn",
    failed: "bad",
    rejected: "bad",
    cancelled: "bad",
    error: "bad",
  };

  // ------------------------------------------------------------------ dom
  const $ = (id) => document.getElementById(id);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = String(value);
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2), value);
      } else if (key === "dataset") Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat(2)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function tone(status) {
    return STATUS_TONE[String(status || "").toLowerCase()] || "";
  }

  function pill(text, status) {
    return el("span", { class: `pill ${tone(status || text)}`, text: String(text ?? "") });
  }

  function kv(key, value) {
    const cell = el("div", {});
    if (value instanceof Node) cell.append(value);
    else cell.textContent = String(value ?? "");
    return [el("div", { class: "k", text: key }), cell];
  }

  function empty(message) {
    return el("div", { class: "muted", text: message });
  }

  function json(value) {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return String(value);
    }
  }

  function cameraText(camera) {
    const entries = Object.entries(camera || {}).slice(0, 3);
    return entries.map(([key, value]) => `${key}:${value}`).join(" · ") || "无运镜信息";
  }

  // ----------------------------------------------------------------- http
  function authHeaders(extra = {}) {
    const headers = { ...extra };
    // The demo identity is an administrator unless it is named explicitly:
    // sending X-User-Id would downgrade it to a plain member, see
    // app.core.security.resolve_user.
    if (state.user && state.user !== "user_demo") headers["X-User-Id"] = state.user;
    if (state.role) headers["X-User-Role"] = state.role;
    return headers;
  }

  async function api(path, { method = "GET", body, form } = {}) {
    const headers = authHeaders();
    let payload;
    if (form) {
      payload = form;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const response = await fetch(API + path, { method, headers, body: payload });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { raw: text };
      }
    }
    if (!response.ok) {
      const message =
        (data && data.error && data.error.message) || `${response.status} ${response.statusText}`;
      const error = new Error(message);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }

  // ------------------------------------------------------------------- log
  function log(message, kind = "") {
    const box = $("log");
    const line = el("div", { class: kind });
    line.append(el("span", { class: "t", text: `${new Date().toLocaleTimeString()}  ` }));
    line.append(document.createTextNode(String(message)));
    box.append(line);
    box.scrollTop = box.scrollHeight;
  }

  function setTask(status, label = "") {
    const node = $("task-pill");
    node.className = `pill ${tone(status)}`;
    node.textContent = status || "idle";
    $("task-label").textContent = label;
  }

  function setProgress(value) {
    const ratio = Math.max(0, Math.min(1, Number(value) || 0));
    $("task-bar").style.width = `${Math.round(ratio * 100)}%`;
  }

  // --------------------------------------------------------------- actions
  function reportTask(label, data) {
    const task = data && data.task;
    if (!task) {
      setTask("succeeded", label);
      log(`${label} 完成`, "ok");
      return;
    }
    const failed = task.status === "failed";
    setTask(task.status, `${label} · ${task.status}`);
    setProgress(task.progress || 0);
    log(`任务 ${task.id} ${task.status}${task.message ? `：${task.message}` : ""}`, failed ? "err" : "ok");
    if (task.error) log(task.error, "err");
  }

  async function post(label, path, body, { wait = true } = {}) {
    try {
      setTask("running", label);
      log(`${label}…`);
      const data = await api(`${path}${wait ? "?wait=true" : ""}`, {
        method: "POST",
        body: body === undefined ? undefined : body,
      });
      reportTask(label, data);
      await refresh();
      return data;
    } catch (error) {
      setTask("failed", label);
      log(`${label} 失败：${error.message}`, "err");
      return null;
    }
  }

  function projectAction(label, suffix, body) {
    if (!state.projectId) {
      log("请先选择或新建项目", "err");
      return Promise.resolve(null);
    }
    return post(label, `/projects/${state.projectId}${suffix}`, body);
  }

  async function decideReview(reviewId, status, comment) {
    try {
      setTask("running", `审核 ${status}`);
      const data = await api(`/reviews/${reviewId}`, {
        method: "POST",
        body: { status, comment: comment || "" },
      });
      log(`审核 ${status === "approved" ? "通过" : "驳回"}（${reviewId}）`, status === "approved" ? "ok" : "warn");
      if (data && data.task_id) await streamTask(data.task_id);
      await refresh();
    } catch (error) {
      setTask("failed", "审核失败");
      log(`审核失败：${error.message}`, "err");
    }
  }

  // ------------------------------------------------------------------- sse
  function handleSseEvent(eventName, payload) {
    if (eventName !== "task") return;
    const level = payload.level || "info";
    const text = `[${payload.event_type}] ${payload.message || ""}`;
    log(text, level === "error" ? "err" : level === "warning" ? "warn" : "");
    setProgress(payload.progress);
    if (TERMINAL.includes(payload.event_type)) {
      setTask(payload.event_type, payload.event_type);
    } else {
      setTask("running", payload.message || payload.event_type);
    }
  }

  async function streamTask(taskId) {
    stopStream();
    const controller = new AbortController();
    state.controller = controller;
    const path = `/projects/${state.projectId}/tasks/${taskId}/events/stream`;
    log(`订阅任务事件流 ${taskId}`);
    try {
      const response = await fetch(API + path, { headers: authHeaders(), signal: controller.signal });
      if (!response.ok || !response.body) throw new Error(`事件流不可用（${response.status}）`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          let eventName = "message";
          const dataLines = [];
          for (const line of chunk.split("\n")) {
            if (!line || line.startsWith(":")) continue;
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (eventName === "end" || eventName === "timeout") {
            log(`事件流结束（${eventName}）`);
            return;
          }
          if (!dataLines.length) continue;
          let payload;
          try {
            payload = JSON.parse(dataLines.join("\n"));
          } catch {
            continue;
          }
          handleSseEvent(eventName, payload);
        }
      }
    } catch (error) {
      if (error.name !== "AbortError") log(`事件流中断：${error.message}`, "err");
    } finally {
      state.controller = null;
    }
  }

  function stopStream() {
    if (state.controller) {
      state.controller.abort();
      state.controller = null;
    }
  }

  // -------------------------------------------------------------- projects
  async function loadProjects() {
    try {
      const { items } = await api("/projects");
      const list = $("project-list");
      list.replaceChildren();
      for (const project of items) {
        list.append(
          el(
            "div",
            {
              class: `project-item${project.id === state.projectId ? " active" : ""}`,
              dataset: { projectId: project.id },
              onclick: () => selectProject(project.id),
            },
            el("div", { class: "name", text: project.name }),
            el("div", {
              class: "meta",
              text: `${project.status} · ${project.genre || "未设题材"} · $${Number(project.spent_usd || 0).toFixed(4)}`,
            }),
          ),
        );
      }
      if (!items.length) list.append(el("div", { class: "small muted", text: "还没有项目。" }));
      if (!items.some((project) => project.id === state.projectId)) {
        state.projectId = items.length ? items[0].id : "";
      }
      if (state.projectId) {
        localStorage.setItem(STORAGE_PROJECT, state.projectId);
        await refresh();
      } else {
        $("dashboard").className = "muted";
        $("dashboard").textContent = "请选择或新建一个项目。";
        $("workbench").className = "muted";
        $("workbench").textContent = "选择项目后加载。";
      }
    } catch (error) {
      log(`加载项目失败：${error.message}`, "err");
    }
  }

  async function selectProject(projectId) {
    stopStream();
    state.projectId = projectId;
    localStorage.setItem(STORAGE_PROJECT, projectId);
    for (const node of document.querySelectorAll(".project-item")) {
      node.classList.toggle("active", node.dataset.projectId === projectId);
    }
    log(`切换到项目 ${projectId}`);
    await refresh();
  }

  async function createProject() {
    const name = $("project-name").value.trim();
    if (!name) {
      log("请填写项目名称", "err");
      return;
    }
    try {
      const project = await api("/projects", { method: "POST", body: { name } });
      $("project-name").value = "";
      log(`创建项目《${project.name}》`, "ok");
      state.projectId = project.id;
      localStorage.setItem(STORAGE_PROJECT, project.id);
      await loadProjects();
    } catch (error) {
      log(`创建项目失败：${error.message}`, "err");
    }
  }

  async function importSample() {
    if (!state.projectId) {
      log("请先选择项目", "err");
      return;
    }
    try {
      setTask("running", "导入示例小说");
      const data = await api(`/projects/${state.projectId}/upload?sample=true`, { method: "POST" });
      log(`已导入示例小说：${data.chapters.length} 章`, "ok");
      setTask("succeeded", "导入示例小说");
      await refresh();
    } catch (error) {
      setTask("failed", "导入示例小说");
      log(`导入失败：${error.message}`, "err");
    }
  }

  async function fullRun() {
    if (!state.projectId) {
      log("请先选择项目", "err");
      return;
    }
    try {
      setTask("running", "一键完整流程");
      log("启动完整工作流…");
      const started = await api(`/projects/${state.projectId}/workflows/start`, {
        method: "POST",
        body: {},
      });
      await streamTask(started.task_id);
      await refresh();
    } catch (error) {
      setTask("failed", "一键完整流程");
      log(`启动失败：${error.message}`, "err");
    }
  }

  async function generateAllCharacterAssets() {
    if (!state.projectId) {
      log("请先选择项目", "err");
      return;
    }
    try {
      const { items } = await api(`/projects/${state.projectId}/characters`);
      if (!items.length) {
        log("还没有角色，先运行剧本解析", "err");
        return;
      }
      for (const character of items) {
        await post(`生成 ${character.name} 形象`, `/characters/${character.id}/generate-images`, {
          kinds: ["portrait", "full_body", "turnaround"],
        });
      }
    } catch (error) {
      log(`生成角色形象失败：${error.message}`, "err");
    }
  }

  // ------------------------------------------------------------- dashboard
  async function loadDashboard() {
    if (!state.projectId) return;
    try {
      const data = await api(`/projects/${state.projectId}/dashboard`);
      renderDashboard(data);
    } catch (error) {
      $("dashboard").className = "muted";
      $("dashboard").replaceChildren(empty(`项目看板加载失败：${error.message}`));
    }
  }

  function renderDashboard(data) {
    const box = $("dashboard");
    box.className = "";
    const project = data.project;
    const summary = data.summary || {};
    const nodes = [];

    nodes.push(
      el(
        "div",
        { class: "kv" },
        kv("项目", `${project.name} ${project.status}`),
        kv("题材 / 语言", `${project.genre || "-"} / ${project.language}`),
        kv(
          "剧本",
          summary.script_title
            ? `${summary.script_title} v${summary.script_version}`
            : "未生成",
        ),
        kv("一句话梗概", summary.logline || "-"),
        kv("人物", (summary.characters || []).join("、") || "-"),
        kv("场景", (summary.scenes || []).join("、") || "-"),
        kv(
          "分镜",
          summary.shot_count
            ? `v${summary.storyboard_version} · ${summary.shot_count} 镜 · ${summary.total_duration_seconds}s`
            : "未生成",
        ),
        kv(
          "成本",
          `$${Number(project.spent_usd || 0).toFixed(4)}${
            project.budget_limit_usd ? ` / $${project.budget_limit_usd}` : ""
          }`,
        ),
        kv("工作流", data.workflow ? `${data.workflow.status}${data.workflow.awaiting_stage ? ` · 待审 ${data.workflow.awaiting_stage}` : ""}` : "未启动"),
      ),
    );

    if (data.evaluation) {
      const scores = Object.entries(data.evaluation.scores || {})
        .map(([key, value]) => `${key} ${Number(value).toFixed(2)}`)
        .join(" · ");
      nodes.push(
        el(
          "div",
          { class: "row", style: "margin-top:10px" },
          pill(`评分 ${Number(data.evaluation.overall_score || 0).toFixed(3)}`, "approved"),
          pill(data.evaluation.recommendation || "-", data.evaluation.recommendation),
          el("span", { class: "small muted", text: scores }),
        ),
      );
    }

    if (data.film && data.film.url) {
      nodes.push(
        el(
          "div",
          { class: "card", style: "margin-top:10px" },
          el("div", { class: "title", text: "成片 / Film" }),
          el("video", { src: data.film.url, controls: true, preload: "metadata" }),
          el("div", { class: "small muted", text: `${data.film.mime_type} · ${data.film.size_bytes} bytes` }),
        ),
      );
    }

    if ((data.pending_reviews || []).length) {
      nodes.push(el("h2", { style: "margin-top:14px", text: "待审核 / Pending reviews" }));
      for (const review of data.pending_reviews) nodes.push(reviewCard(review));
    }

    if ((data.tasks || []).length) {
      nodes.push(el("h2", { style: "margin-top:14px", text: "最近任务 / Recent tasks" }));
      const rows = el("div", { class: "stack" });
      for (const task of data.tasks.slice(0, 6)) {
        rows.append(
          el(
            "div",
            { class: "row small" },
            pill(task.status, task.status),
            el("span", { text: `${task.type} · ${task.message || ""}` }),
            el("span", { class: "spacer" }),
            el("span", { class: "muted", text: task.finished_at || task.created_at || "" }),
          ),
        );
      }
      nodes.push(rows);
    }

    box.replaceChildren(...nodes);
  }

  function reviewCard(review) {
    const comment = el("textarea", { placeholder: "审核意见（可留空）", style: "min-height:64px" });
    return el(
      "div",
      { class: "card", style: "margin-top:8px" },
      el(
        "div",
        { class: "title" },
        `阶段 ${review.stage} `,
        pill(review.status, review.status),
        el("span", { class: "small muted", text: ` ${review.created_at || ""}` }),
      ),
      review.comment ? el("div", { class: "small muted", text: `意见：${review.comment}` }) : null,
      comment,
      el(
        "div",
        { class: "row", style: "margin-top:6px" },
        el("button", { class: "ok", onclick: () => decideReview(review.id, "approved", comment.value) }, "通过并继续"),
        el("button", { class: "bad", onclick: () => decideReview(review.id, "rejected", comment.value) }, "驳回"),
      ),
    );
  }

  // ---------------------------------------------------------------- tabs
  const TABS = [
    { id: "story", label: "剧本", render: renderStory },
    { id: "characters", label: "角色", render: renderCharacters },
    { id: "scenes", label: "场景", render: renderScenes },
    { id: "director", label: "导演", render: renderDirector },
    { id: "shots", label: "分镜", render: renderShots },
    { id: "videos", label: "视频", render: renderVideos },
    { id: "audio", label: "配音字幕", render: renderAudio },
    { id: "editing", label: "剪辑", render: renderEditing },
    { id: "quality", label: "质量评估", render: renderQuality },
    { id: "reviews", label: "审核", render: renderReviews },
    { id: "admin", label: "模型配置", render: renderAdmin },
  ];

  function renderTabs() {
    const bar = $("tabs");
    bar.replaceChildren();
    for (const tab of TABS) {
      bar.append(
        el(
          "button",
          {
            class: tab.id === state.tab ? "active" : "",
            onclick: () => {
              state.tab = tab.id;
              renderTabs();
              paintActive();
            },
          },
          tab.label,
        ),
      );
    }
  }

  async function paint(renderer) {
    const box = $("workbench");
    if (!state.projectId) {
      box.className = "muted";
      box.textContent = "选择项目后加载。";
      return;
    }
    box.className = "";
    const token = ++state.renderToken;
    try {
      const content = await renderer();
      if (token !== state.renderToken) return;
      box.replaceChildren(content);
    } catch (error) {
      if (token !== state.renderToken) return;
      box.replaceChildren(
        el(
          "div",
          { class: "card" },
          el("div", { class: "title", text: "加载失败" }),
          el("div", { class: "sub", text: error.message }),
        ),
      );
    }
  }

  function paintActive() {
    const tab = TABS.find((item) => item.id === state.tab) || TABS[0];
    return paint(tab.render);
  }

  async function refresh() {
    await loadDashboard();
    await paintActive();
  }

  // ---------------------------------------------------------------- story
  async function renderStory() {
    const projectId = state.projectId;
    const [documents, chapters, scripts] = await Promise.all([
      api(`/projects/${projectId}/documents`),
      api(`/projects/${projectId}/chapters`),
      api(`/projects/${projectId}/scripts`),
    ]);

    const wrapper = el("div", { class: "stack" });
    const file = el("input", { type: "file", accept: ".txt,.md,.docx" });
    file.style.maxWidth = "260px";
    wrapper.append(
      el(
        "div",
        { class: "row" },
        file,
        el("button", { onclick: () => uploadDocument(file) }, "上传小说"),
        el("button", { onclick: importSample }, "导入示例"),
        el(
          "span",
          { class: "small muted" },
          `文档 ${documents.count} · 章节 ${chapters.count} · 剧本版本 ${scripts.count}`,
        ),
      ),
    );

    const chapterGrid = el("div", { class: "grid" });
    for (const chapter of chapters.items) {
      chapterGrid.append(
        el(
          "div",
          { class: "card" },
          el("div", { class: "title", text: `第 ${chapter.index + 1} 章 ${chapter.title || ""}` }),
          el("div", { class: "sub", text: `${chapter.word_count || 0} 字` }),
          el("div", { class: "small", text: (chapter.summary || chapter.content || "").slice(0, 160) }),
        ),
      );
    }
    if (!chapters.items.length) chapterGrid.append(empty("还没有章节，先导入小说。"));
    wrapper.append(chapterGrid);

    wrapper.append(el("h2", { style: "margin-top:12px", text: "剧本 / Script" }));
    if (!scripts.items.length) {
      wrapper.append(empty("还没有剧本，运行「剧本解析」生成。"));
      return wrapper;
    }
    const script = await api(`/projects/${projectId}/script`);
    const title = el("input", { value: script.title || "" });
    const logline = el("input", { value: script.logline || "" });
    const synopsis = el("textarea", { style: "min-height:90px" });
    synopsis.value = script.synopsis || "";
    const content = el("textarea", {});
    content.value = json(script.content);

    wrapper.append(
      el(
        "div",
        { class: "card" },
        el("div", { class: "row" }, pill(`v${script.version}`, script.status), pill(script.status, script.status)),
        el("div", { class: "inline-grid", style: "margin-top:8px" },
          el("label", { class: "small muted" }, "标题", title),
          el("label", { class: "small muted" }, "一句话梗概", logline),
        ),
        el("label", { class: "small muted" }, "剧情梗概", synopsis),
        el("label", { class: "small muted" }, "结构化内容（JSON，结构需符合剧本 schema）", content),
        el(
          "div",
          { class: "row", style: "margin-top:8px" },
          el(
            "button",
            {
              class: "primary",
              onclick: () =>
                saveScript(script.id, {
                  title: title.value,
                  logline: logline.value,
                  synopsis: synopsis.value,
                  content: parseJson(content, "剧本内容"),
                }),
            },
            "保存剧本",
          ),
          el("span", { class: "small muted", text: `事件 ${script.events.length} 条` }),
        ),
      ),
    );
    return wrapper;
  }

  function parseJson(node, label) {
    const text = node.value.trim();
    if (!text) return undefined;
    try {
      return JSON.parse(text);
    } catch (error) {
      log(`${label} JSON 解析失败：${error.message}`, "err");
      throw error;
    }
  }

  async function uploadDocument(file) {
    if (!file.files || !file.files.length) {
      log("请先选择小说文件", "err");
      return;
    }
    const form = new FormData();
    form.append("file", file.files[0]);
    try {
      setTask("running", "上传小说");
      const data = await api(`/projects/${state.projectId}/upload`, { method: "POST", form });
      log(`已导入 ${data.document.filename}：${data.chapters.length} 章`, "ok");
      setTask("succeeded", "上传小说");
      await refresh();
    } catch (error) {
      setTask("failed", "上传小说");
      log(`上传失败：${error.message}`, "err");
    }
  }

  async function saveScript(scriptId, patch) {
    try {
      await api(`/scripts/${scriptId}`, { method: "PATCH", body: patch });
      log("剧本已保存", "ok");
      await refresh();
    } catch (error) {
      log(`保存剧本失败：${error.message}`, "err");
    }
  }

  // ----------------------------------------------------------- characters
  async function renderCharacters() {
    const { items } = await api(`/projects/${state.projectId}/characters`);
    if (!items.length) return empty("还没有角色，先运行「剧本解析」。");
    const grid = el("div", { class: "grid" });
    for (const character of items) {
      const assets = el("div", { class: "grid" });
      const summary = el("textarea", { style: "min-height:70px" });
      summary.value = character.summary || "";
      const keywords = el("input", { value: (character.appearance_keywords || []).join(", ") });
      const card = el(
        "div",
        { class: "card" },
        el("div", { class: "title" }, `${character.name} `, pill(character.status, character.status)),
        el("div", { class: "sub", text: character.role_type || "" }),
        el("label", { class: "small muted" }, "人物小传", summary),
        el("label", { class: "small muted" }, "外形关键词（逗号分隔）", keywords),
        el(
          "div",
          { class: "row", style: "margin-top:6px" },
          el(
            "button",
            {
              onclick: () =>
                saveCharacter(character.id, {
                  summary: summary.value,
                  appearance_keywords: keywords.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                }),
            },
            "保存",
          ),
          el(
            "button",
            { onclick: () => post(`生成 ${character.name} 形象`, `/characters/${character.id}/generate-images`, { kinds: ["portrait", "full_body", "turnaround"] }) },
            "生成形象",
          ),
          el(
            "button",
            { onclick: () => post(`生成 ${character.name} 三视图`, `/characters/${character.id}/generate-views`, {}) },
            "三视图",
          ),
          el(
            "button",
            { class: "ok", onclick: () => post(`通过 ${character.name}`, `/characters/${character.id}/approve`) },
            "通过",
          ),
        ),
        assets,
      );
      grid.append(card);
      api(`/characters/${character.id}/assets`)
        .then((data) => paintAssets(assets, data.items))
        .catch(() => paintAssets(assets, []));
    }
    return grid;
  }

  function paintAssets(box, items) {
    box.replaceChildren();
    if (!items.length) {
      box.append(el("div", { class: "sub", text: "暂无素材" }));
      return;
    }
    for (const item of items) {
      const card = el(
        "div",
        { class: "card" },
        el("div", { class: "sub", text: `${item.kind} v${item.version}${item.approved ? " · 已通过" : ""}` }),
      );
      if (item.url) card.append(el("img", { src: item.url, alt: item.kind, loading: "lazy" }));
      box.append(card);
    }
  }

  async function saveCharacter(characterId, patch) {
    try {
      await api(`/characters/${characterId}`, { method: "PATCH", body: patch });
      log("人物设定已保存", "ok");
      await refresh();
    } catch (error) {
      log(`保存失败：${error.message}`, "err");
    }
  }

  // --------------------------------------------------------------- scenes
  async function renderScenes() {
    const { items } = await api(`/projects/${state.projectId}/scenes`);
    if (!items.length) return empty("还没有场景，先运行「剧本解析」。");
    const grid = el("div", { class: "grid" });
    for (const scene of items) {
      const summary = el("textarea", { style: "min-height:70px" });
      summary.value = scene.summary || "";
      grid.append(
        el(
          "div",
          { class: "card" },
          el("div", { class: "title" }, scene.name, " ", pill(scene.approved_version ? "已通过" : "草稿", scene.approved_version ? "approved" : "pending")),
          el("div", { class: "sub", text: `第 ${(scene.chapter_index ?? 0) + 1} 章` }),
          el("div", { class: "small", text: scene.visual_prompt || "" }),
          el("label", { class: "small muted" }, "场景说明", summary),
          el(
            "div",
            { class: "row", style: "margin-top:6px" },
            el("button", { onclick: () => saveScene(scene.id, { summary: summary.value }) }, "保存"),
            el("button", { class: "ok", onclick: () => post(`通过 ${scene.name}`, `/scenes/${scene.id}/approve`) }, "通过"),
          ),
        ),
      );
    }
    return grid;
  }

  async function saveScene(sceneId, patch) {
    try {
      await api(`/scenes/${sceneId}`, { method: "PATCH", body: patch });
      log("场景已保存", "ok");
      await refresh();
    } catch (error) {
      log(`保存失败：${error.message}`, "err");
    }
  }

  // ------------------------------------------------------------- director
  async function renderDirector() {
    const projectId = state.projectId;
    const wrapper = el("div", { class: "stack" });
    const directing = await api(`/projects/${projectId}/directing`);
    if (!directing.plan) {
      wrapper.append(empty("还没有导演规划，点击「导演规划」生成。"));
    } else {
      wrapper.append(
        el(
          "div",
          { class: "card" },
          el(
            "div",
            { class: "row" },
            pill(`v${directing.plan.version}`, directing.plan.status),
            pill(directing.plan.approved ? "已通过" : "待审核", directing.plan.approved ? "approved" : "pending"),
            el("span", { class: "small muted", text: directing.plan.model_id || "" }),
          ),
          el("pre", { class: "small", text: json(directing.plan.content) }),
        ),
      );
    }
    if (directing.versions.length) {
      wrapper.append(
        el(
          "div",
          { class: "row small muted" },
          el("span", { text: "历史版本：" }),
          ...directing.versions.map((row) => pill(`v${row.version}`, row.status)),
        ),
      );
    }
    return wrapper;
  }

  // ---------------------------------------------------------------- shots
  async function renderShots() {
    const { board } = await api(`/projects/${state.projectId}/storyboards`);
    if (!board) return empty("还没有分镜，点击「生成分镜」。");
    const wrapper = el("div", { class: "stack" });
    wrapper.append(
      el(
        "div",
        { class: "row" },
        pill(`分镜 v${board.version}`, board.status),
        pill(board.approved ? "已通过" : "待审核", board.approved ? "approved" : "pending"),
        el("span", { class: "small muted", text: `${board.shots.length} 个镜头` }),
      ),
    );
    for (const shot of board.shots) wrapper.append(shotCard(shot));
    return wrapper;
  }

  function shotCard(shot) {
    const prompt = el("textarea", { style: "min-height:76px" });
    prompt.value = shot.visual_prompt || "";
    return el(
      "div",
      { class: "card", style: "margin-top:8px" },
      el("div", { class: "title" }, `#${shot.order} ${shot.description || ""} `, pill(shot.status || "-", shot.status)),
      el(
        "div",
        { class: "sub" },
        `${shot.duration_seconds}s · ${cameraText(shot.camera)} · ${
          (shot.characters || []).map((item) => item.character_name).join("、") || "无角色"
        }`,
      ),
      shot.action ? el("div", { class: "small", text: shot.action }) : null,
      el("label", { class: "small muted" }, "视觉提示词", prompt),
      el(
        "div",
        { class: "row", style: "margin-top:6px" },
        el("button", { onclick: () => saveShot(shot.id, { visual_prompt: prompt.value }) }, "保存提示词"),
        el("button", { class: "ok", onclick: () => post(`通过镜头 #${shot.order}`, `/shots/${shot.id}/approve`) }, "通过"),
        el("button", { onclick: () => post(`生成镜头 #${shot.order} 视频`, `/shots/${shot.id}/generate`) }, "生成视频"),
      ),
    );
  }

  async function saveShot(shotId, patch) {
    try {
      await api(`/shots/${shotId}`, { method: "PATCH", body: patch });
      log("镜头已保存", "ok");
      await refresh();
    } catch (error) {
      log(`保存镜头失败：${error.message}`, "err");
    }
  }

  // --------------------------------------------------------------- videos
  async function renderVideos() {
    const { items } = await api(`/projects/${state.projectId}/shots`);
    if (!items.length) return empty("还没有镜头，先生成分镜。");
    const wrapper = el("div", { class: "stack" });
    for (const shot of items) {
      const versions = await api(`/shots/${shot.id}/versions`);
      const grid = el("div", { class: "grid" });
      if (!versions.items.length) grid.append(empty("暂无视频版本"));
      for (const video of versions.items) {
        const card = el(
          "div",
          { class: "card" },
          el("div", { class: "sub", text: `v${video.version} · ${video.status}${video.selected ? " · 当前使用" : ""}` }),
        );
        if (video.url) card.append(el("video", { src: video.url, controls: true, preload: "metadata" }));
        else if (video.error) card.append(el("div", { class: "small", text: video.error }));
        card.append(
          el(
            "div",
            { class: "row", style: "margin-top:6px" },
            el(
              "button",
              {
                class: video.selected ? "primary" : "",
                disabled: video.selected,
                onclick: () => post("选用视频", `/shots/${shot.id}/versions/${video.id}/select`, undefined, { wait: false }),
              },
              video.selected ? "已选用" : "选用",
            ),
          ),
        );
        grid.append(card);
      }
      wrapper.append(
        el(
          "div",
          { class: "card", style: "margin-top:8px" },
          el("div", { class: "title" }, `#${shot.order} ${shot.description || ""} `, pill(shot.status, shot.status)),
          grid,
        ),
      );
    }
    return wrapper;
  }

  // ---------------------------------------------------------------- audio
  async function renderAudio() {
    const { items } = await api(`/projects/${state.projectId}/audio`);
    if (!items.length) return empty("还没有音轨，点击「生成配音」。");
    const wrapper = el("div", { class: "stack" });
    for (const track of items) {
      const card = el(
        "div",
        { class: "card" },
        el("div", { class: "small muted", text: `${track.kind} · ${track.status} · ${track.duration_seconds}s · 起始 ${track.start_seconds}s` }),
        el("div", { class: "small", text: track.text || "" }),
      );
      if (track.url) card.append(el("audio", { src: track.url, controls: true, preload: "none" }));
      else if (track.error) card.append(el("div", { class: "small", text: track.error }));
      wrapper.append(card);
    }
    return wrapper;
  }

  // -------------------------------------------------------------- editing
  async function renderEditing() {
    const data = await api(`/projects/${state.projectId}/editing`);
    const wrapper = el("div", { class: "stack" });
    if (!data.editing) {
      wrapper.append(empty("还没有时间线，点击「编排时间线」。"));
      return wrapper;
    }
    wrapper.append(
      el(
        "div",
        { class: "card" },
        el(
          "div",
          { class: "row" },
          pill(`编辑 v${data.editing.version}`, data.editing.status),
          el("span", { class: "small muted", text: `时长 ${data.editing.duration_seconds}s` }),
        ),
        el("pre", { class: "small", text: json(data.editing.timeline) }),
      ),
    );
    if (data.editing.output_url) {
      wrapper.append(
        el(
          "div",
          { class: "card" },
          el("div", { class: "title", text: "成片" }),
          el("video", { src: data.editing.output_url, controls: true, preload: "metadata" }),
        ),
      );
    }
    if (data.editing.subtitle_url) {
      wrapper.append(el("a", { href: data.editing.subtitle_url, target: "_blank", class: "small" }, "下载字幕 SRT"));
    }
    if (data.versions.length) {
      wrapper.append(
        el(
          "div",
          { class: "row small muted" },
          el("span", { text: "历史版本：" }),
          ...data.versions.map((row) => pill(`v${row.version} · ${row.duration_seconds}s`, row.status)),
        ),
      );
    }
    return wrapper;
  }

  // -------------------------------------------------------------- quality
  async function renderQuality() {
    const data = await api(`/projects/${state.projectId}/evaluation`);
    const wrapper = el("div", { class: "stack" });
    if (!data.evaluation) {
      wrapper.append(empty("还没有评估报告，点击「质量评估」。"));
    } else {
      const evaluation = data.evaluation;
      const grid = el("div", { class: "grid" });
      for (const [dimension, score] of Object.entries(evaluation.scores || {})) {
        grid.append(
          el(
            "div",
            { class: "card" },
            el("div", { class: "title", text: dimension }),
            el("div", { class: "sub", text: Number(score).toFixed(3) }),
          ),
        );
      }
      wrapper.append(
        el(
          "div",
          { class: "card" },
          el(
            "div",
            { class: "row" },
            pill(`总分 ${Number(evaluation.overall_score || 0).toFixed(3)}`, "approved"),
            pill(evaluation.recommendation || "-", evaluation.recommendation),
          ),
          el("div", { class: "small", text: evaluation.summary || "" }),
          grid,
        ),
      );
      if ((evaluation.issues || []).length) {
        const issues = el("div", { class: "stack" });
        for (const issue of evaluation.issues) {
          issues.append(
            el(
              "div",
              { class: "row small" },
              pill(issue.severity || "-", issue.severity),
              el("span", { text: `${issue.type}: ${issue.description}` }),
            ),
          );
        }
        wrapper.append(el("h2", { text: "问题 / Issues" }), issues);
      }
    }
    wrapper.append(el("h2", { text: "指标 / Metrics" }), el("pre", { class: "small", text: json(data.metrics) }));
    return wrapper;
  }

  // -------------------------------------------------------------- reviews
  async function renderReviews() {
    const { items } = await api(`/projects/${state.projectId}/reviews`);
    if (!items.length) return empty("还没有审核记录，运行工作流后会在审核门产出一条。");
    const wrapper = el("div", { class: "stack" });
    for (const review of items) {
      const card = reviewCard(review);
      if (review.status !== "pending") {
        card.replaceChildren(
          el(
            "div",
            { class: "title" },
            `阶段 ${review.stage} `,
            pill(review.status, review.status),
            el("span", { class: "small muted", text: ` ${review.reviewed_at || review.created_at || ""}` }),
          ),
          el("div", { class: "small", text: review.comment || "（无意见）" }),
          el(
            "div",
            { class: "small muted", text: `评论 ${(review.comments || []).length} 条` },
          ),
        );
      }
      wrapper.append(card);
    }
    return wrapper;
  }

  // ---------------------------------------------------------------- admin
  async function renderAdmin() {
    const wrapper = el("div", { class: "stack" });
    let status = null;
    try {
      status = await api("/admin/status");
    } catch (error) {
      wrapper.append(
        el(
          "div",
          { class: "card" },
          el("div", { class: "title", text: "需要管理员身份" }),
          el("div", { class: "sub", text: `切换到 admin 角色后重试：${error.message}` }),
        ),
      );
      return wrapper;
    }
    wrapper.append(
      el(
        "div",
        { class: "kv" },
        kv("环境", status.env),
        kv("数据库", status.database),
        kv("存储", `${status.storage_backend} · ${status.storage_root}`),
        kv("FFmpeg", `${status.ffmpeg.bin} · ${status.ffmpeg.available ? "可用" : "缺失"}`),
        kv("任务", `${status.tasks.inline ? "inline" : "pool"} · ${status.tasks.max_workers} workers`),
        kv("智能体", `${status.agents.enabled}/${status.agents.count} 启用`),
        kv("配置版本", json(status.config_versions)),
      ),
    );

    const { items } = await api("/admin/model-configs");
    const table = el("div", { class: "stack" });
    const editor = el("div", {});
    for (const item of items) {
      table.append(
        el(
          "div",
          { class: "row small" },
          pill(item.enabled ? "启用" : "停用", item.enabled ? "approved" : "pending"),
          el("span", { text: `${item.id} · ${item.provider}/${item.model_id}` }),
          el("span", { class: "spacer" }),
          el("button", { onclick: () => openAgentEditor(item.id, editor) }, "版本编辑"),
        ),
      );
    }
    wrapper.append(el("h2", { text: "模型配置 / Model configs" }), table, editor);
    return wrapper;
  }

  async function openAgentEditor(agentId, container) {
    try {
      const data = await api(`/admin/model-configs/${agentId}`);
      const payload = el("textarea", {});
      payload.value = json(data.payload);
      const note = el("input", { placeholder: "变更说明" });
      container.replaceChildren(
        el(
          "div",
          { class: "card", style: "margin-top:8px" },
          el("div", { class: "title", text: `${agentId} · 新配置版本` }),
          el("div", { class: "sub", text: `现有版本 ${data.versions.length} 个（最新 v${data.versions[0]?.version ?? 0}）` }),
          el("label", { class: "small muted" }, "完整智能体配置（JSON，保存后立即生效）", payload),
          el("label", { class: "small muted" }, "变更说明", note),
          el(
            "div",
            { class: "row", style: "margin-top:8px" },
            el(
              "button",
              { class: "primary", onclick: () => saveAgentConfig(agentId, payload, note, container) },
              "保存为新版本",
            ),
            el("button", { onclick: () => openAgentEditor(agentId, container) }, "重置"),
            el("button", { class: "bad", onclick: () => resetAgentConfig(agentId) }, "回退到 YAML"),
          ),
        ),
      );
    } catch (error) {
      log(`加载配置失败：${error.message}`, "err");
    }
  }

  async function saveAgentConfig(agentId, payload, note, container) {
    try {
      const body = { payload: parseJson(payload, "智能体配置"), note: note.value };
      const data = await api(`/admin/model-configs/${agentId}/versions`, { method: "POST", body });
      log(`已写入 ${agentId} 配置 v${data.version.version}`, "ok");
      container.replaceChildren();
      await refresh();
    } catch (error) {
      log(`保存配置失败：${error.message}`, "err");
    }
  }

  async function resetAgentConfig(agentId) {
    try {
      await api(`/admin/model-configs/${agentId}/override`, { method: "DELETE" });
      log(`${agentId} 已回退到 YAML 配置`, "ok");
      await refresh();
    } catch (error) {
      log(`回退失败：${error.message}`, "err");
    }
  }

  // ----------------------------------------------------------------- boot
  async function boot() {
    $("user-input").value = state.user;
    $("role-input").value = state.role;

    $("user-input").addEventListener("change", () => {
      state.user = $("user-input").value.trim() || "user_demo";
      localStorage.setItem(STORAGE_USER, state.user);
      loadProjects();
    });
    $("role-input").addEventListener("change", () => {
      state.role = $("role-input").value;
      localStorage.setItem(STORAGE_ROLE, state.role);
      loadProjects();
    });

    $("create-project").addEventListener("click", createProject);
    $("refresh-projects").addEventListener("click", loadProjects);
    $("btn-full-run").addEventListener("click", fullRun);
    $("btn-sample").addEventListener("click", importSample);
    $("btn-analyze").addEventListener("click", () => projectAction("剧本解析", "/analyze"));
    $("btn-directing").addEventListener("click", () => projectAction("导演规划", "/direct"));
    $("btn-storyboard").addEventListener("click", () => projectAction("生成分镜", "/storyboards"));
    $("btn-character-assets").addEventListener("click", generateAllCharacterAssets);
    $("btn-video").addEventListener("click", () => projectAction("生成视频", "/shots/generate"));
    $("btn-audio").addEventListener("click", () => projectAction("生成配音", "/audio"));
    $("btn-editing").addEventListener("click", () => projectAction("编排时间线", "/editing"));
    $("btn-render").addEventListener("click", () => projectAction("合成成片", "/render"));
    $("btn-evaluate").addEventListener("click", () => projectAction("质量评估", "/evaluate"));
    $("btn-export").addEventListener("click", () => projectAction("导出 MP4", "/export"));
    $("clear-log").addEventListener("click", () => $("log").replaceChildren());

    renderTabs();
    setTask("idle", "");

    try {
      const health = await fetch("/health").then((response) => response.json());
      const node = $("health-pill");
      node.className = `pill ${health.status === "ok" ? "ok" : "bad"}`;
      node.textContent = health.status === "ok" ? "服务正常" : "服务异常";
    } catch {
      $("health-pill").className = "pill bad";
      $("health-pill").textContent = "离线";
    }

    try {
      const meta = await api("/meta");
      state.meta = meta;
      $("env-label").textContent = `${meta.env} · ${meta.storage_backend} · ${meta.agents.length} agents`;
    } catch (error) {
      $("env-label").textContent = "meta 加载失败";
      log(`读取 /meta 失败：${error.message}`, "err");
    }

    await loadProjects();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
