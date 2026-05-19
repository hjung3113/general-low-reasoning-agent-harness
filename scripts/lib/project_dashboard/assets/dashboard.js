const app = document.querySelector("#app");

const routes = {
  "/": "overview",
  "/overview": "overview",
  "/progress": "progress",
  "/actions": "actions",
};

let state = null;

window.addEventListener("popstate", render);
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-route]");
  if (!link) return;
  event.preventDefault();
  history.pushState({}, "", link.getAttribute("href"));
  render();
});

load();

async function load() {
  const response = await fetch("/api/dashboard", { cache: "no-store" });
  state = await response.json();
  render();
}

function render() {
  const route = routes[window.location.pathname] || "overview";
  document.querySelectorAll("nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
  if (!state) return;
  if (route === "progress") renderProgress();
  else if (route === "actions") renderActions();
  else renderOverview();
}

function renderOverview() {
  const project = state.project;
  const gate = state.gate;
  const done = state.roadmap.filter((phase) => phase.completed).length;
  const active = firstOpenPhase();
  app.innerHTML = `
    ${warnings()}
    <section class="grid">
      <article class="panel span-8">
        <p class="eyebrow">${escape(project.milestone)}</p>
        <h2>${escape(project.milestone_name)}</h2>
        <p class="muted">${escape(project.status)}</p>
        <div class="progress"><span style="width:${bounded(project.progress_percent)}%"></span></div>
        <p><strong>${project.completed_phases}/${project.total_phases}</strong> phases complete from planning state.</p>
      </article>
      <article class="panel span-4">
        <h2>Current Gate</h2>
        ${pill(gate.phase)} ${pill(gate.approved ? "approved" : "not approved")} ${pill(gate.automation_mode)}
        <p><code>${escape(project.active_checkpoint)}</code></p>
      </article>
      <article class="panel span-4">
        <h2>Completed</h2>
        <p class="metric">${done}</p>
        <p class="muted">Roadmap phases marked done.</p>
      </article>
      <article class="panel span-4">
        <h2>Active</h2>
        <p>${active ? escape(active.title) : "No active phase inferred."}</p>
      </article>
      <article class="panel span-4">
        <h2>Next Action</h2>
        <p>${escape(project.next_action)}</p>
      </article>
      <article class="panel span-12">
        <h2>Milestones</h2>
        <div class="timeline">${state.roadmap.map(phaseCard).join("")}</div>
      </article>
    </section>`;
}

function renderProgress() {
  const gate = state.gate;
  app.innerHTML = `
    ${warnings()}
    <section class="grid">
      <article class="panel span-6">
        <h2>Detailed Gate State</h2>
        ${detail("Phase", gate.phase)}
        ${detail("Plan", gate.plan_id)}
        ${detail("Checkpoint", gate.current_checkpoint)}
        ${detail("Approved By", gate.approved_by)}
        ${detail("Approved At", gate.approved_at)}
      </article>
      <article class="panel span-6">
        <h2>Verification</h2>
        ${list(gate.verification, true)}
      </article>
      <article class="panel span-6">
        <h2>Acceptance Criteria</h2>
        ${list(gate.acceptance_criteria)}
      </article>
      <article class="panel span-6">
        <h2>Allowed Paths</h2>
        ${list(gate.allowed_paths, true)}
        <h2 style="margin-top:18px">Blocked Paths</h2>
        ${list(gate.blocked_paths, true)}
      </article>
      <article class="panel span-12">
        <h2>Phase Documents</h2>
        <div class="cards">${state.phase_documents.map(docCard).join("") || "<p>No phase documents found.</p>"}</div>
      </article>
      <article class="panel span-12">
        <h2>Requirements</h2>
        <div class="cards">${state.memory.requirements.map(reqCard).join("") || "<p>No requirements found.</p>"}</div>
      </article>
    </section>`;
}

function renderActions() {
  app.innerHTML = `
    ${warnings()}
    <section class="grid">
      <article class="panel span-12">
        <h2>CLI Actions</h2>
        <p class="muted">Buttons call allowlisted local commands through the Python server. They do not accept arbitrary shell input.</p>
      </article>
      <article class="panel span-8">
        <div class="timeline">${state.actions.map(actionRow).join("")}</div>
      </article>
      <article class="panel span-4">
        <h2>Latest Output</h2>
        <pre id="output">No command has run in this browser session.</pre>
      </article>
    </section>`;
  document.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button));
  });
}

async function runAction(button) {
  const action = state.actions.find((item) => item.id === button.dataset.action);
  if (!action) return;
  const confirmed = action.confirmation ? window.confirm(action.confirmation) : false;
  if (action.confirmation && !confirmed) return;
  button.disabled = true;
  setOutput(`$ ${action.command}\n\nrunning...`);
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action: action.id, confirmed }),
    });
    const result = await response.json();
    setOutput(`$ ${result.command || action.command}\nexit ${result.returncode ?? "n/a"}\n\n${result.output || result.error || ""}`);
    await load();
  } finally {
    button.disabled = false;
  }
}

function firstOpenPhase() {
  return state.roadmap.find((phase) => !phase.completed);
}

function phaseCard(phase) {
  const active = !phase.completed && firstOpenPhase() === phase;
  const cls = phase.completed ? "done" : active ? "active" : "";
  return `<article class="phase ${cls}"><h3>${escape(phase.title)}</h3><p>${escape(phase.summary || "")}</p>${pill(phase.completed ? "done" : active ? "in progress" : "remaining")}</article>`;
}

function docCard(doc) {
  const files = Object.entries(doc.files || {}).map(([name, path]) => `<span class="pill">${escape(name)}</span>`).join("");
  return `<article class="card"><h3>${escape(doc.phase_dir)}</h3><p>${escape((doc.headings || []).slice(0, 3).join(" / "))}</p>${files}</article>`;
}

function reqCard(req) {
  return `<article class="card"><h3>${escape(req.id)}</h3><p>${escape(req.summary)}</p></article>`;
}

function actionRow(action) {
  const style = action.confirmation ? "warning" : action.id === "next" ? "secondary" : "";
  return `<div class="command-row"><div><h3>${escape(action.label)}</h3><p class="muted">${escape(action.description)}</p><code>${escape(action.command)}</code></div><button class="${style}" data-action="${escape(action.id)}">${escape(action.label)}</button></div>`;
}

function warnings() {
  if (!state.warnings.length) return "";
  return `<section class="panel warning-box"><h2>Warnings</h2>${list(state.warnings)}</section>`;
}

function detail(label, value) {
  return `<p><span class="muted">${escape(label)}</span><br><code>${escape(value || "unknown")}</code></p>`;
}

function list(items, code = false) {
  if (!items || !items.length) return "<p class=\"muted\">None recorded.</p>";
  return `<ul>${items.map((item) => `<li>${code ? `<code>${escape(item)}</code>` : escape(item)}</li>`).join("")}</ul>`;
}

function pill(value) {
  return `<span class="pill">${escape(value)}</span>`;
}

function setOutput(value) {
  const output = document.querySelector("#output");
  if (output) output.textContent = value;
}

function bounded(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function escape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
