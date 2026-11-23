/* Local drafts are removed only after an explicit server acknowledgement. */
(() => {
  "use strict";
  const grid = document.querySelector("#grade-grid");
  if (!grid) return;
  const form = document.querySelector("#sync-form");
  const summary = document.querySelector("#sync-summary");
  const warning = document.querySelector("#storage-warning");
  const inputs = new Map([...grid.querySelectorAll(".grade-input")].map(el => [el.dataset.key, el]));
  if (!inputs.size) return;
  const messages = JSON.parse(document.getElementById("grade-grid-messages").textContent);
  const formatMessage = (key, values) => messages[key].replace(/%\((\w+)\)s/g, (_, name) => String(values[name]));
  const pending = new Map();
  let batch = null, timer, paused = false, storageOK = true;
  const prefix = ["urafiki", "v1", grid.dataset.user, grid.dataset.class, grid.dataset.period].join(":") + ":";
  const start = () => {
    function storageError() {
      storageOK = false;
      warning.hidden = false;
      warning.textContent = messages.extra2;
    }
    function persist(key, draft) {
      try {
        if (draft) localStorage.setItem(prefix + key, JSON.stringify(draft));
        else localStorage.removeItem(prefix + key);
      } catch (_) { storageError(); }
    }
    function state(input, status, message) {
      input.closest("td").dataset.state = status;
      input.setAttribute("aria-invalid", status === "error" ? "true" : "false");
      document.getElementById("status-" + input.dataset.key).textContent = message;
      input.closest("td").querySelector(".discard-cell").hidden = !pending.has(input.dataset.key);
    }
    function announce(message) {
      summary.textContent = message || (pending.size
        ? formatMessage("pending", {count: pending.size, connection: !navigator.onLine ? messages.offline : ""})
        : messages.m0);
    }
    function schedule(delay = 500) { clearTimeout(timer); timer = setTimeout(flush, delay); }
    function flush() {
      if (batch || paused || !navigator.onLine || !window.htmx) { announce(); return; }
      const entries = [...pending.entries()].filter(([, draft]) => !draft.error).slice(0, 30);
      if (!entries.length) { announce(); return; }
      batch = new Map(entries.map(([key, draft]) => [key, {...draft}]));
      document.querySelector("#sync-changes").value = JSON.stringify(entries.map(([key, draft]) => {
        const input = inputs.get(key);
        state(input, "saving", messages.m1);
        return {enrollment: Number(input.dataset.enrollment), course: Number(input.dataset.course), value: draft.value, base: draft.base};
      }));
      announce(formatMessage("saving_count", {count: entries.length}));
      htmx.trigger(form, "sync-grades");
    }
    for (const [key, input] of inputs) {
      let draft;
      try {
        draft = JSON.parse(localStorage.getItem(prefix + key) || "null");
        if (draft && (typeof draft.value !== "string" || typeof draft.base !== "string")) throw Error("invalid draft");
      } catch (_) { storageError(); }
      if (input.dataset.locked !== "true") input.disabled = false;
      if (draft) {
        pending.set(key, draft);
        input.value = draft.value;
        if (input.disabled) { draft.error = true; state(input, "error", messages.m2); }
        else state(input, draft.error ? "error" : "local", draft.error ? messages.m3 : messages.m4);
      }
    }
    grid.addEventListener("input", event => {
      const input = event.target;
      if (!input.matches(".grade-input")) return;
      const key = input.dataset.key;
      const value = input.value.trim();
      const previous = pending.get(key);
      const draft = {value, base: previous ? previous.base : input.dataset.base, error: false};
      pending.set(key, draft);
      persist(key, draft);
      state(input, "local", storageOK ? messages.m5 : messages.m6);
      announce(); schedule();
    });
    grid.addEventListener("keydown", event => {
      const input = event.target;
      if (!input.matches(".grade-input") || event.altKey || event.ctrlKey || event.metaKey) return;
      const row = input.closest("tr"), cells = [...row.querySelectorAll(".grade-input")];
      const column = cells.indexOf(input);
      let target;
      if (event.key === "ArrowUp") target = row.previousElementSibling?.querySelectorAll(".grade-input")[column];
      if (event.key === "ArrowDown" || event.key === "Enter") target = row.nextElementSibling?.querySelectorAll(".grade-input")[column];
      if (event.key === "ArrowLeft" && input.selectionStart === 0) target = cells[column - 1];
      if (event.key === "ArrowRight" && input.selectionEnd === input.value.length) target = cells[column + 1];
      if (target && !target.disabled) { event.preventDefault(); target.focus(); target.select(); }
    });
    grid.addEventListener("click", event => {
      if (!event.target.matches(".discard-cell") || batch) return;
      const key = event.target.dataset.key, input = inputs.get(key);
      pending.delete(key); persist(key, null);
      input.value = input.dataset.base;
      state(input, "saved", input.disabled ? messages.m7 : messages.m8);
      announce();
    });
    form.addEventListener("htmx:afterRequest", event => {
      if (!batch) return;
      const xhr = event.detail.xhr;
      const sent = batch; batch = null;
      const valid = [200, 422].includes(xhr.status) && xhr.getResponseHeader("X-Grade-Sync") === "1";
      if (valid) {
        const documentResult = new DOMParser().parseFromString(xhr.responseText, "text/html");
        const results = new Map([...documentResult.querySelectorAll("[data-sync-results] [data-key]")].map(el => [el.dataset.key, el]));
        for (const [key, submitted] of sent) {
          const draft = pending.get(key), input = inputs.get(key), result = results.get(key);
          if (!draft || !result) { if (draft) state(input, "local", messages.extra4); continue; }
          if (result.dataset.state === "saved") {
            input.dataset.base = result.dataset.base;
            if (draft.value === submitted.value) {
              pending.delete(key); persist(key, null);
              state(input, "saved", messages.m9);
            } else {
              draft.base = result.dataset.base; persist(key, draft);
              state(input, "local", messages.extra5);
            }
          } else if (draft.value === submitted.value) {
            draft.error = true; persist(key, draft);
            state(input, "error", result.textContent);
          }
        }
        schedule();
      } else {
        paused = [400, 401, 403].includes(xhr.status) || (xhr.status === 200 && !valid);
        const message = paused ? messages.m10 : messages.m11;
        for (const key of sent.keys()) if (pending.has(key)) state(inputs.get(key), paused ? "error" : "local", message);
        if (paused) { warning.hidden = false; warning.textContent = message; }
        else schedule(5000);
      }
      announce();
    });
    document.querySelector("#retry-sync").addEventListener("click", () => {
      if (paused) { announce(messages.m12); return; }
      for (const [key, draft] of pending) if (!inputs.get(key).disabled) { draft.error = false; persist(key, draft); }
      schedule(0);
    });
    document.querySelector("#export-drafts").addEventListener("click", () => {
      const csv = [[messages.m13, messages.m14, messages.m15, messages.m16, messages.m17], ...[...pending].map(([key, d]) => [grid.dataset.class, grid.dataset.period, key, d.value, d.base])];
      const content = csv.map(row => row.map(value => '"' + String(value).replace(/^[=+@-]/, "'$&").replaceAll('"', '""') + '"').join(";")).join("\r\n");
      const url = URL.createObjectURL(new Blob(["\uFEFF", content], {type: "text/csv;charset=utf-8"}));
      const link = document.createElement("a"); link.href = url; link.download = "urafiki-brouillons.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    window.addEventListener("online", () => schedule(0));
    window.addEventListener("offline", () => announce());
    window.addEventListener("beforeunload", event => { if (pending.size) { event.preventDefault(); event.returnValue = ""; } });
    if (!window.htmx) { paused = true; warning.hidden = false; warning.textContent = messages.m18; }
    announce(); schedule();
  };
  if (navigator.locks) {
    navigator.locks.request(prefix, {ifAvailable: true}, async lock => {
      if (!lock) {
        summary.textContent = messages.extra7;
        return;
      }
      start();
      await new Promise(() => {});
    });
  } else {
    summary.textContent = messages.extra8;
  }
})();

