// Talos Linux sidebar panel. Vanilla web component, no build step.
// Reads cluster/node data from the talos_linux/get websocket command and
// renders a Nodes view that matches the Home Assistant look via theme vars.

const REFRESH_MS = 10000;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

const pct = (v) => (v == null ? "–" : `${Math.round(v)}%`);

function fmtUptime(boot) {
  if (!boot) return "–";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - boot));
  const d = Math.floor(s / 86400);
  if (d >= 1) return `${d}d`;
  const h = Math.floor(s / 3600);
  if (h >= 1) return `${h}h`;
  return `${Math.floor(s / 60)}m`;
}

function fmtGiB(kb) {
  if (!kb) return "–";
  return `${(kb / 1024 / 1024).toFixed(2)} GiB`;
}

function barColor(v) {
  if (v == null) return "var(--disabled-text-color, #888)";
  if (v >= 90) return "var(--error-color, #db4437)";
  if (v >= 75) return "var(--warning-color, #ffa600)";
  return "var(--primary-color, #03a9f4)";
}

function meter(label, v) {
  const w = v == null ? 0 : Math.min(100, Math.max(0, v));
  return `<span class="meter"><span class="meter-label">${label}</span>
    <span class="track"><span class="fill" style="width:${w}%;background:${barColor(v)}"></span></span>
    <span class="meter-val">${pct(v)}</span></span>`;
}

function field(label, value, mono = false) {
  return `<div class="field"><div class="flabel">${esc(label)}</div>
    <div class="fvalue${mono ? " mono" : ""}">${esc(value ?? "–")}</div></div>`;
}

function detail(node) {
  const ext = (node.extensions || [])
    .filter((e) => e.name && e.name !== "schematic")
    .map((e) => `<span class="chip">${esc(e.name)}<span class="chip-v">${esc(e.version || "")}</span></span>`)
    .join("");
  const svc = (node.services || [])
    .map((s) => `<span class="chip ${s.healthy ? "ok" : "bad"}">${esc(s.id)}</span>`)
    .join("");
  const etcd = (node.etcd_members || [])
    .map((m) => `<span class="chip">${esc(m.hostname || m.id)}${m.is_learner ? " (learner)" : ""}</span>`)
    .join("");

  const memUsed =
    node.memory_total && node.memory_used_pct != null
      ? `${fmtGiB((node.memory_total * node.memory_used_pct) / 100)} / ${fmtGiB(node.memory_total)}`
      : pct(node.memory_used_pct);

  return `<div class="detail">
    <div class="grid">
      ${field("Internal IP", node.address, true)}
      ${field("Role", node.role || "–")}
      ${field("Talos version", node.version)}
      ${field("Machine stage", node.stage)}
      ${field("Platform", node.platform)}
      ${field("Architecture", node.arch)}
      ${field("CPU usage", pct(node.cpu_pct))}
      ${field("Memory", memUsed)}
      ${field("System disk", pct(node.disk_used_pct))}
      ${field("Uptime", fmtUptime(node.boot_time))}
      ${field("Schematic", node.schematic ? node.schematic.slice(0, 16) + "…" : "–", true)}
      ${field("Ready", node.ready == null ? "–" : node.ready ? "Yes" : "No")}
    </div>
    ${ext ? `<div class="section"><div class="slabel">System extensions</div><div class="chips">${ext}</div></div>` : ""}
    ${svc ? `<div class="section"><div class="slabel">Services</div><div class="chips">${svc}</div></div>` : ""}
    ${etcd ? `<div class="section"><div class="slabel">etcd members</div><div class="chips">${etcd}</div></div>` : ""}
  </div>`;
}

function row(node, key, expanded) {
  const badge = !node.online
    ? `<span class="badge off">Offline</span>`
    : node.ready
      ? `<span class="badge ready">Ready</span>`
      : `<span class="badge notready">Not Ready</span>`;
  return `<div class="node ${expanded ? "open" : ""}" data-key="${esc(key)}">
    <div class="node-head" data-toggle="${esc(key)}">
      <span class="chev">${expanded ? "▾" : "▸"}</span>
      <span class="name">${esc(node.hostname || node.address)}</span>
      <span class="spacer"></span>
      ${badge}
      <span class="ip mono">${esc(node.address)}</span>
      ${meter("CPU", node.cpu_pct)}
      ${meter("MEM", node.memory_used_pct)}
      <span class="uptime">${fmtUptime(node.boot_time)}</span>
    </div>
    ${expanded ? detail(node) : ""}
  </div>`;
}

const STYLE = `
  :host { display:block; }
  .wrap { padding:16px 24px; max-width:1600px; margin:0 auto;
    color:var(--primary-text-color); font-family:var(--paper-font-body1_-_font-family, sans-serif); }
  .controls { display:flex; gap:12px; align-items:center; margin:8px 0 16px; flex-wrap:wrap; }
  input.search { background:var(--card-background-color,#1c1c1c); color:var(--primary-text-color);
    border:1px solid var(--divider-color,#333); border-radius:8px; padding:8px 12px; min-width:240px; outline:none; }
  .filters { display:flex; gap:8px; }
  .filters button { background:transparent; color:var(--secondary-text-color); border:1px solid var(--divider-color,#333);
    border-radius:16px; padding:5px 14px; cursor:pointer; }
  .filters button.active { background:var(--primary-color); color:var(--text-primary-color,#fff); border-color:var(--primary-color); }
  .count { color:var(--secondary-text-color); font-size:13px; margin-left:auto; }
  .cluster-title { font-size:15px; color:var(--secondary-text-color); margin:18px 0 8px; }
  .node { background:var(--card-background-color,#1c1c1c); border:1px solid var(--divider-color,#2a2a2a);
    border-radius:12px; margin-bottom:8px; overflow:hidden; }
  .node.open { border-color:var(--primary-color); }
  .node-head { display:flex; align-items:center; gap:14px; padding:14px 16px; cursor:pointer; }
  .node-head:hover { background:var(--secondary-background-color, rgba(255,255,255,0.03)); }
  .chev { color:var(--secondary-text-color); width:12px; }
  .name { font-weight:600; }
  .spacer { flex:1; }
  .badge { font-size:12px; padding:2px 10px; border-radius:12px; }
  .badge.ready { color:#1f8a4c; background:rgba(31,138,76,0.18); }
  .badge.notready { color:#c0392b; background:rgba(192,57,43,0.18); }
  .badge.off { color:var(--secondary-text-color); background:rgba(128,128,128,0.18); }
  .ip { color:var(--secondary-text-color); font-size:13px; min-width:92px; }
  .mono { font-family:var(--code-font-family, monospace); }
  .meter { display:flex; align-items:center; gap:6px; }
  .meter-label { color:var(--secondary-text-color); font-size:11px; }
  .track { width:80px; height:6px; border-radius:3px; background:var(--divider-color,#333); overflow:hidden; }
  .fill { display:block; height:100%; border-radius:3px; }
  .meter-val { font-size:12px; min-width:34px; text-align:right; color:var(--secondary-text-color); }
  .uptime { color:var(--secondary-text-color); font-size:13px; min-width:42px; text-align:right; }
  .detail { padding:6px 16px 18px 42px; border-top:1px solid var(--divider-color,#2a2a2a); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:14px 24px; margin:14px 0; }
  .flabel { color:var(--secondary-text-color); font-size:11px; text-transform:uppercase; letter-spacing:.4px; }
  .fvalue { margin-top:2px; }
  .section { margin-top:10px; }
  .slabel { color:var(--secondary-text-color); font-size:11px; text-transform:uppercase; letter-spacing:.4px; margin-bottom:6px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { display:inline-flex; align-items:center; gap:6px; background:var(--secondary-background-color,#2a2a2a);
    border:1px solid var(--divider-color,#333); border-radius:14px; padding:3px 10px; font-size:12px; }
  .chip-v { color:var(--secondary-text-color); font-size:11px; }
  .chip.ok { border-color:rgba(31,138,76,0.5); }
  .chip.bad { border-color:rgba(192,57,43,0.6); color:#e07a6f; }
  .empty { color:var(--secondary-text-color); padding:40px; text-align:center; }
`;

class TalosLinuxPanel extends HTMLElement {
  constructor() {
    super();
    this._data = null;
    this._expanded = new Set();
    this._search = "";
    this._filter = "all";
    this._timer = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._fetch();
  }

  connectedCallback() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="wrap">
        <div class="controls">
          <input class="search" type="text" placeholder="Search nodes…" />
          <div class="filters">
            <button data-f="all" class="active">All</button>
            <button data-f="ready">Ready</button>
            <button data-f="notready">Not Ready</button>
          </div>
          <span class="count"></span>
        </div>
        <div class="list"></div>
      </div>`;

    this.shadowRoot.querySelector(".search").addEventListener("input", (e) => {
      this._search = e.target.value.toLowerCase();
      this._renderList();
    });
    this.shadowRoot.querySelectorAll(".filters button").forEach((b) =>
      b.addEventListener("click", () => {
        this._filter = b.dataset.f;
        this.shadowRoot.querySelectorAll(".filters button").forEach((x) =>
          x.classList.toggle("active", x === b)
        );
        this._renderList();
      })
    );
    this.shadowRoot.querySelector(".list").addEventListener("click", (e) => {
      const head = e.target.closest("[data-toggle]");
      if (!head) return;
      const key = head.dataset.toggle;
      if (this._expanded.has(key)) this._expanded.delete(key);
      else this._expanded.add(key);
      this._renderList();
    });

    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
    if (this._data) this._renderList();
  }

  disconnectedCallback() {
    if (this._timer) clearInterval(this._timer);
  }

  async _fetch() {
    if (!this._hass) return;
    try {
      this._data = await this._hass.connection.sendMessagePromise({
        type: "talos_linux/get",
      });
    } catch (err) {
      this._data = { clusters: [], error: String(err) };
    }
    this._renderList();
  }

  _renderList() {
    const list = this.shadowRoot && this.shadowRoot.querySelector(".list");
    if (!list) return;
    const clusters = (this._data && this._data.clusters) || [];

    if (!clusters.length) {
      list.innerHTML = `<div class="empty">No Talos clusters configured, or no nodes reachable yet.</div>`;
      this.shadowRoot.querySelector(".count").textContent = "";
      return;
    }

    let total = 0;
    let ready = 0;
    let html = "";
    const multi = clusters.length > 1;
    for (const c of clusters) {
      let nodes = c.nodes || [];
      total += nodes.length;
      ready += nodes.filter((n) => n.ready).length;
      if (this._search)
        nodes = nodes.filter((n) =>
          (n.hostname || n.address || "").toLowerCase().includes(this._search)
        );
      if (this._filter === "ready") nodes = nodes.filter((n) => n.ready);
      if (this._filter === "notready") nodes = nodes.filter((n) => !n.ready);

      if (multi) html += `<div class="cluster-title">${esc(c.title)}</div>`;
      html += nodes
        .map((n) => {
          const key = `${c.entry_id}|${n.address}`;
          return row(n, key, this._expanded.has(key));
        })
        .join("");
    }
    list.innerHTML = html;
    this.shadowRoot.querySelector(".count").textContent =
      `${ready}/${total} nodes ready`;
  }
}

customElements.define("talos-linux-panel", TalosLinuxPanel);
