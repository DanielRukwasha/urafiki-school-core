/* Local drafts are removed only after an explicit server acknowledgement. */
(() => {
  "use strict";
  const grid = document.querySelector("#grade-grid");
  if (!grid) return;
  const form = document.querySelector("#sync-form");
  const summary = document.querySelector("#sync-summary");
  const warning = document.querySelector("#storage-warning");
  const inputs = new Map([...grid.querySelectorAll(".grade-input")].map(el => [el.dataset.key, el]));
  const pending = new Map();
  let batch = null, timer, paused = false, storageOK = true;
  const prefix = ["urafiki", "v1", grid.dataset.user, grid.dataset.class, grid.dataset.period].join(":") + ":";
  const start = () => {
    function storageError() {
      storageOK = false;
      warning.hidden = false;
      warning.textContent = "Stockage local indisponible. Gardez cette page ouverte et exportez vos brouillons avant de quitter.";
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
        ? pending.size + " cote(s) en attente" + (!navigator.onLine ? " · Hors connexion" : "")
        : "Toutes les cotes sont enregistrées");
    }
    function schedule(delay = 500) { clearTimeout(timer); timer = setTimeout(flush, delay); }
    function flush() {
      if (batch || paused || !navigator.onLine || !window.htmx) { announce(); return; }
      const entries = [...pending.entries()].filter(([, draft]) => !draft.error).slice(0, 30);
      if (!entries.length) { announce(); return; }
      batch = new Map(entries.map(([key, draft]) => [key, {...draft}]));
      document.querySelector("#sync-changes").value = JSON.stringify(entries.map(([key, draft]) => {
        const input = inputs.get(key);
        state(input, "saving", "Enregistrement…");
        return {enrollment: Number(input.dataset.enrollment), course: Number(input.dataset.course), value: draft.value, base: draft.base};
      }));
      announce("Enregistrement de " + entries.length + " cote(s)…");
      htmx.trigger(form, "sync-grades");
    }
    for (const [key, input] of inputs) {
      let draft;
      try {
        draft = JSON.parse(localStorage.getItem(prefix + key) || "null");
        if (draft && (typeof draft.value !== "string" || typeof draft.base !== "string")) throw Error("invalid draft");
      } catch (_) { storageError(); }
      if (input.dataset.locked !== "true" && input.dataset.editable === "true") input.disabled = false;
      if (draft) {
        pending.set(key, draft);
        input.value = draft.value;
        if (input.disabled) { draft.error = true; state(input, "error", input.dataset.editable === "true" ? "Cote verrouillée. Exportez ou abandonnez le brouillon." : "Lecture seule : cote d’un autre enseignant."); }
        else state(input, draft.error ? "error" : "local", draft.error ? "Brouillon à vérifier" : "Brouillon local restauré");
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
      state(input, "local", storageOK ? "Brouillon local" : "Brouillon en mémoire");
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
      state(input, "saved", input.disabled ? "Verrouillée" : "Cote serveur restaurée");
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
          if (!draft || !result) { if (draft) state(input, "local", "Confirmation manquante. Nouvel essai…"); continue; }
          if (result.dataset.state === "saved") {
            input.dataset.base = result.dataset.base;
            if (draft.value === submitted.value) {
              pending.delete(key); persist(key, null);
              state(input, "saved", "Enregistré sur le serveur");
            } else {
              draft.base = result.dataset.base; persist(key, draft);
              state(input, "local", "Nouvelle modification en attente");
            }
          } else if (draft.value === submitted.value) {
            draft.error = true; persist(key, draft);
            state(input, "error", result.textContent);
          }
        }
        schedule();
      } else {
        paused = [400, 401, 403].includes(xhr.status) || (xhr.status === 200 && !valid);
        const message = paused ? "Session ou requête refusée. Reconnectez-vous puis rechargez cette page ; vos brouillons sont conservés." : "Connexion interrompue. Brouillon conservé.";
        for (const key of sent.keys()) if (pending.has(key)) state(inputs.get(key), paused ? "error" : "local", message);
        if (paused) { warning.hidden = false; warning.textContent = message; }
        else schedule(5000);
      }
      announce();
    });
    document.querySelector("#retry-sync").addEventListener("click", () => {
      if (paused) { announce("Rechargez la page après reconnexion pour reprendre les brouillons."); return; }
      for (const [key, draft] of pending) if (!inputs.get(key).disabled) { draft.error = false; persist(key, draft); }
      schedule(0);
    });
    document.querySelector("#export-drafts").addEventListener("click", () => {
      const csv = [["Classe", "Période", "Cellule", "Cote", "Base serveur"], ...[...pending].map(([key, d]) => [grid.dataset.class, grid.dataset.period, key, d.value, d.base])];
      const content = csv.map(row => row.map(value => '"' + String(value).replace(/^[=+@-]/, "'$&").replaceAll('"', '""') + '"').join(";")).join("\r\n");
      const url = URL.createObjectURL(new Blob(["\uFEFF", content], {type: "text/csv;charset=utf-8"}));
      const link = document.createElement("a"); link.href = url; link.download = "urafiki-brouillons.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    window.addEventListener("online", () => schedule(0));
    window.addEventListener("offline", () => announce());
    window.addEventListener("beforeunload", event => { if (pending.size) { event.preventDefault(); event.returnValue = ""; } });
    if (!window.htmx) { paused = true; warning.hidden = false; warning.textContent = "La synchronisation ne peut pas démarrer. Rechargez la page ; exportez vos brouillons si nécessaire."; }
    announce(); schedule();
  };
  if (navigator.locks) {
    navigator.locks.request(prefix, {ifAvailable: true}, async lock => {
      if (!lock) {
        summary.textContent = "Cette grille est ouverte dans un autre onglet. Fermez cet onglet puis rechargez ici.";
        return;
      }
      start();
      await new Promise(() => {});
    });
  } else {
    summary.textContent = "La saisie requiert un navigateur moderne et une connexion HTTPS.";
  }
})();

