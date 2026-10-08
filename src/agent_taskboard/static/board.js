const stateLabels = {
  not_started: "Not started",
  in_progress: "In progress",
  done: "Done",
  excluded: "Cancelled",
};
const badgeLabels = {
  waiting_review: "Waiting for review",
  failed: "Failed",
  blocked: "Blocked",
  stale: "Not updated",
  unknown: "Unknown",
};

const offline = document.querySelector("#offline");
const openList = document.querySelector("#open-list");
const doneList = document.querySelector("#done-list");
const empty = document.querySelector("#empty");
const counts = document.querySelector("#counts");
const search = document.querySelector("#search");
const pin = document.querySelector("#pin");
const statusFilter = document.querySelector("#status-filter");
let snapshot = { tasks: [], counts: { not_started: 0, in_progress: 0, done: 0 }, server_time: null };

function showOffline(on) {
  offline.classList.toggle("show", on);
}

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value == null ? "" : String(value);
  if (className) node.className = className;
  return node;
}

function safeHref(kind, value) {
  if (kind === "http" && /^https?:\/\//i.test(value)) return value;
  if (kind === "opencode" && value.startsWith("opencode://")) return value;
  return null;
}

function addLink(list, kind, value, label) {
  const href = safeHref(kind, value);
  const item = document.createElement("li");
  if (!href) {
    item.append(text("span", label + ": "));
    item.append(text("span", value, "path"));
    const button = text("button", "Copy path");
    button.type = "button";
    button.addEventListener("click", () => navigator.clipboard.writeText(value));
    item.append(button);
  } else {
    const link = document.createElement("a");
    link.href = href;
    link.textContent = label;
    link.rel = "noopener noreferrer";
    if (kind === "http") link.target = "_blank";
    item.append(link);
  }
  list.append(item);
}

function reportedText(iso, serverTime) {
  const when = new Date(iso);
  const base = serverTime ? new Date(serverTime) : new Date();
  const minutes = Math.max(0, Math.round((base.getTime() - when.getTime()) / 60000));
  const relative = minutes < 1 ? "just now" : minutes < 60 ? minutes + "m ago" : Math.round(minutes / 60) + "h ago";
  return relative + " · " + when.toLocaleString();
}

function card(task) {
  const article = document.createElement("article");
  article.className = "card";
  article.append(text("h2", task.title));
  const row = document.createElement("div");
  row.className = "status-row";
  const state = text("span", stateLabels[task.ui_state] || task.ui_state, "tag");
  if (task.ui_state === "done") state.classList.add("done");
  if (task.ui_state === "in_progress") state.classList.add("progress");
  row.append(state);
  for (const badge of task.badges || []) {
    row.append(text("span", badgeLabels[badge] || badge, "tag badge"));
  }
  article.append(row);
  article.append(text("p", task.task_id, "meta"));
  const goal = document.createElement("p");
  goal.className = "goal";
  goal.append(text("strong", "Goal: "));
  goal.append(document.createTextNode(task.task));
  article.append(goal);
  const deliver = document.createElement("p");
  deliver.className = "deliver";
  deliver.append(text("strong", "Expected deliverable: "));
  deliver.append(document.createTextNode(task.expected_deliverable));
  article.append(deliver);
  const reported = text("p", "Last reported: " + reportedText(task.last_reported_at, snapshot.server_time), "meta");
  reported.title = task.last_reported_at;
  article.append(reported);
  const links = document.createElement("ul");
  links.className = "links";
  for (const ref of task.result_refs || []) addLink(links, ref.kind, ref.value, ref.label);
  if (task.owner_session_ref) addLink(links, "opencode", task.owner_session_ref, "Session");
  article.append(links);
  const attempt = document.createElement("details");
  attempt.append(text("summary", "Attempt"));
  attempt.append(text("p", task.attempt_id || "No attempt yet", "meta"));
  if (task.outcome) attempt.append(text("p", task.outcome));
  article.append(attempt);
  return article;
}

function visibleTasks() {
  const needle = search.value.trim().toLocaleLowerCase();
  const wanted = statusFilter.value;
  return snapshot.tasks.filter((task) => {
    if (wanted && task.ui_state !== wanted) return false;
    if (!needle) return true;
    const haystack = [task.task_id, task.title, task.task, task.expected_deliverable, task.group_id].join(" ").toLocaleLowerCase();
    return haystack.includes(needle);
  });
}

function fillPin() {
  const selected = pin.value;
  const groups = [...new Set(snapshot.tasks.map((task) => task.group_id))];
  pin.replaceChildren();
  const all = text("option", "All groups");
  all.value = "";
  pin.append(all);
  for (const group of groups) {
    const option = text("option", group);
    option.value = group;
    pin.append(option);
  }
  pin.value = groups.includes(selected) ? selected : "";
}

function render() {
  const tasks = visibleTasks();
  const pinned = pin.value;
  const open = tasks.filter((task) => task.ui_state !== "done");
  open.sort((a, b) => Number(b.group_id === pinned) - Number(a.group_id === pinned));
  const done = tasks.filter((task) => task.ui_state === "done");
  openList.replaceChildren(...open.map(card));
  doneList.replaceChildren(...done.map(card));
  empty.hidden = tasks.length !== 0;
  counts.textContent = "Not started " + snapshot.counts.not_started + " · In progress " + snapshot.counts.in_progress + " · Done " + snapshot.counts.done;
}

let generation = 0;

async function refresh() {
  const ticket = ++generation;
  try {
    const response = await fetch("/tasks", { cache: "no-store" });
    if (ticket !== generation) return;
    if (!response.ok) throw new Error("snapshot");
    snapshot = await response.json();
    if (ticket !== generation) return;
    showOffline(false);
    fillPin();
    render();
  } catch (_error) {
    if (ticket !== generation) return;
    showOffline(true);
  }
}

search.addEventListener("input", render);
pin.addEventListener("change", render);
statusFilter.addEventListener("change", render);
refresh();
const source = new EventSource("/events");
source.onopen = () => refresh();
source.addEventListener("change", () => refresh());
source.onerror = () => showOffline(true);
