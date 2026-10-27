/* Campus Carbon Tracker dashboard. Reads docs/data/*.json (written by `python -m pipeline.run`).
   Every headline below is computed from those files at render time. */
(function () {
  "use strict";

  const SOURCE_NAMES = {
    electricity: "Electricity meters", gas: "Natural gas bills", refrigerants: "Refrigerant top-ups",
    fleet: "Fleet fuel cards", renewables: "Renewable electricity purchases", flights: "Business flights",
    waste: "Waste collections",
  };
  const SCEN_VARS = {
    "Business as usual": "--sc-bau", "Rooftop solar expansion": "--sc-solar", "Gas to heat pumps": "--sc-heat",
    "100% renewable PPA": "--sc-ppa", "All three combined": "--sc-all",
  };
  const SCEN_LABEL = {
    "Business as usual": "No new action", "Rooftop solar expansion": "More rooftop solar",
    "Gas to heat pumps": "Gas heating to heat pumps", "100% renewable PPA": "100% renewable power contract",
    "All three combined": "All three combined",
  };
  const label = (s) => SCEN_LABEL[s] || s;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const state = { fy: null, method: "market", scen: new Set(["Business as usual", "All three combined"]) };
  let D = {};
  const charts = {};

  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString("en-AU", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const monthLabel = (ym, withYear) => MONTHS[+ym.slice(5, 7) - 1] + (withYear ? " " + ym.slice(0, 4) : "");
  const hh = (h) => String(h).padStart(2, "0") + ":00";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const wrap = (txt, n) => txt.split(" ").reduce((lines, w) => {
    const last = lines[lines.length - 1];
    if (last && (last + " " + w).length <= n) lines[lines.length - 1] = last + " " + w; else lines.push(w);
    return lines;
  }, []).join("\n");
  const fyShort = (y) => "FY" + (y - 1) + "-" + String(y % 100).padStart(2, "0");

  function chart(id) {
    if (!charts[id]) charts[id] = echarts.init($(id), null, { renderer: "svg" });
    return charts[id];
  }

  function base() {
    const ink2 = css("--ink-2"), hair = css("--hair"), axis = css("--axis");
    return {
      textStyle: { fontFamily: css("--font"), color: ink2 },
      grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
      tooltip: {
        backgroundColor: css("--surface"), borderColor: hair, textStyle: { color: css("--ink"), fontSize: 13 },
        extraCssText: "border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);",
      },
      axisCommon: {
        axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
        splitLine: { lineStyle: { color: hair, type: "solid" } }, axisLabel: { color: ink2 },
        nameTextStyle: { color: ink2, align: "left" },
      },
    };
  }

  // axis options: shared look first, then the axis' own settings; axisLabel is merged, not replaced
  function ax(spec, extra) {
    const common = base().axisCommon;
    return Object.assign({}, common, spec, extra || {},
      { axisLabel: Object.assign({}, common.axisLabel, spec.axisLabel, (extra || {}).axisLabel) });
  }

  // ---------------- KPIs ----------------
  function renderKpis() {
    const s = D.summary.by_fy[state.fy], k = s.kpis, p = D.pathway;
    const isBase = state.fy === D.summary.baseline_fy;
    const ch = k.change_vs_baseline_pct;
    const dir = ch < 0 ? "down" : "up";
    const progress = Math.max(0, Math.min(100, k.progress_to_2030_pct));
    const cutNeeded = p.baseline - p.target_2030, cutDone = p.baseline - k.scope12_t;
    const health = D.health[state.fy];
    const open = health.reduce((a, r) => a + r.open_issues, 0);
    const card = (cls, label, value, unit, sub, meter) =>
      `<div class="kpi ${cls}"><div class="label">${label}</div><div class="value">${value}<small>${unit}</small></div>` +
      (meter != null ? `<div class="meter" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${meter}"><i style="width:${meter}%"></i></div>` : "") +
      `<div class="sub">${sub}</div></div>`;
    $("kpis").innerHTML = [
      card("lead", "Total emissions, all scopes", fmt(k.total_t), "t CO2-e",
        (isBase ? "Baseline year that targets are measured from" :
          `<span class="${dir}">${dir === "down" ? "▼" : "▲"} ${fmt(Math.abs(ch), 1)}%</span> on ${D.summary.baseline_fy}`) +
        `<br>${fmt(k.total_location_t)} t without green power purchases`),
      card("", "Progress to 2030 target", fmt(progress), "%",
        isBase ? `Target: cut energy and fuel emissions by ${fmt(cutNeeded)} t by 2030` :
          `of the cut needed: ${fmt(Math.max(cutDone, 0))} t done, ${fmt(Math.max(cutNeeded - cutDone, 0))} t to go`, progress),
      card("", "Emissions per student", fmt(k.per_student_kg), "kg CO2-e", `${fmt(k.students)} students`),
      card("", "Renewable electricity", fmt(k.renewable_share_pct), "%", "Green power bought plus rooftop solar", Math.min(100, k.renewable_share_pct)),
      card("", "Data quality score", fmt(k.dq_score, k.dq_score % 1 ? 1 : 0), "/ 100", open ? `${open} open issue${open > 1 ? "s" : ""} across ${health.length} sources` : `No open issues across ${health.length} sources`),
    ].join("");
  }

  // ---------------- emissions by scope ----------------
  function renderScope() {
    const s = D.summary.by_fy[state.fy], m = s.monthly, b = base();
    const s2 = state.method === "market" ? m.s2_market : m.s2_location;
    const key = state.method === "market" ? "t" : "t_location";
    const total = s.sources.reduce((a, r) => a + r[key], 0);
    const top = [...s.sources].sort((a, c) => c[key] - a[key])[0];
    $("h-scope").textContent = `${top.source} is ${fmt(100 * top[key] / total)}% of campus emissions in ${state.fy}`;
    const surface = css("--surface");
    const ser = (name, data, color, last) => ({
      name, type: "bar", stack: "t", data, barMaxWidth: 24,
      itemStyle: { color, borderColor: surface, borderWidth: 1, borderRadius: last ? [4, 4, 0, 0] : 0 },
      emphasis: { focus: "series" },
    });
    chart("c-scope").setOption({
      textStyle: b.textStyle, grid: b.grid,
      tooltip: Object.assign({}, b.tooltip, {
        trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: css("--accent-wash"), opacity: 0.6 } },
        formatter: (ps) => {
          const t = ps.reduce((a, p) => a + (p.value || 0), 0);
          return `<b>${monthLabel(m.months[ps[0].dataIndex], true)}</b><br>` +
            ps.slice().reverse().map((p) => `${p.marker} ${p.seriesName}: <b>${fmt(p.value)}</b> t`).join("<br>") +
            `<br>Total: <b>${fmt(t)}</b> t CO2-e`;
        },
      }),
      legend: { show: false },
      xAxis: ax({ type: "category", data: m.months.map((x) => monthLabel(x)) }, { splitLine: { show: false } }),
      yAxis: ax({ type: "value", name: "t CO2-e", axisLabel: { color: css("--ink-2"), formatter: (v) => (v >= 1000 ? v / 1000 + "K" : v) } }),
      series: [ser("Scope 1", m.s1, css("--s1")), ser("Scope 2", s2, css("--s2")), ser("Scope 3", m.s3, css("--s3"), true)],
    }, true);
  }

  // ---------------- Net Zero pathway ----------------
  function renderPathway() {
    const p = D.pathway, b = base(), ink = css("--ink"), muted = css("--muted"), surface = css("--surface");
    const years = p.years, lastActual = p.actual.filter((v) => v != null).length - 1;
    const now = p.actual[lastActual], cut = 100 * (1 - now / p.baseline);
    const bau = p.summary.find((x) => x.scenario === "Business as usual");
    $("h-path").textContent = `Energy and fuel emissions are down ${fmt(cut)}% since ${D.summary.baseline_fy}, ` +
      (bau.meets_2030 ? "enough to meet the 2030 target" : `but another ${fmt(bau.gap_to_2030_target_t)} t must go to meet the 2030 target`);

    $("scenario-chips").innerHTML = p.summary.map((x) =>
      `<button type="button" class="chip" aria-pressed="${state.scen.has(x.scenario)}" data-scen="${esc(x.scenario)}">` +
      `<span class="sw line" style="background:var(${SCEN_VARS[x.scenario]})"></span>${esc(label(x.scenario))}</button>`).join("");

    const endLabel = (txt) => ({ show: true, formatter: txt, color: css("--ink-2"), fontSize: 12, distance: 6 });
    const series = [
      { name: "Target", type: "line", data: p.target, symbol: "none", lineStyle: { color: muted, width: 2, type: [6, 4] }, z: 1,
        endLabel: endLabel("Target") },
      { name: "Actual", type: "line", data: p.actual, symbol: "circle", symbolSize: 9, z: 5,
        lineStyle: { color: ink, width: 2.5 }, itemStyle: { color: ink, borderColor: surface, borderWidth: 2 } },
    ];
    p.summary.forEach((x) => {
      if (!state.scen.has(x.scenario)) return;
      const c = css(SCEN_VARS[x.scenario]);
      series.push({ name: label(x.scenario), type: "line", data: p.scenarios[x.scenario], symbol: "none", z: 3,
        lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, endLabel: endLabel(label(x.scenario)) });
    });
    chart("c-path").setOption({
      animation: false,  // end labels on lines with leading nulls animate through NaN positions
      textStyle: b.textStyle, grid: Object.assign({}, b.grid, { right: window.innerWidth < 520 ? 118 : 150 }),
      tooltip: Object.assign({}, b.tooltip, {
        trigger: "axis",
        formatter: (ps) => `<b>${fyShort(years[ps[0].dataIndex])}</b><br>` + ps.filter((q) => q.value != null)
          .map((q) => `${q.marker} ${q.seriesName}: <b>${fmt(q.value)}</b> t`).join("<br>"),
      }),
      xAxis: ax({ type: "category", data: years.map(String), boundaryGap: false }, { splitLine: { show: false } }),
      yAxis: ax({ type: "value", min: 0, name: "t CO2-e (Scope 1 + 2)", axisLabel: { color: css("--ink-2"), formatter: (v) => (v >= 1000 ? v / 1000 + "K" : v) } }),
      series,
    }, true);

    const opts = p.summary.filter((x) => x.scenario !== "Business as usual" && x.scenario !== "All three combined");
    const best = opts.reduce((a, c) => (c.abated_vs_bau_t > a.abated_vs_bau_t ? c : a));
    const worst = opts.reduce((a, c) => (c.abated_vs_bau_t < a.abated_vs_bau_t ? c : a));
    const all = p.summary.find((x) => x.scenario === "All three combined");
    const items = [
      `<li><b>Biggest single step:</b> a ${esc(label(best.scenario).toLowerCase())} cuts ${fmt(best.abated_vs_bau_t)} t a year by 2030${best.meets_2030 ? ", enough on its own to meet the target" : ""}.</li>`,
      `<li><b>All three together</b> leave ${fmt(all.t_2030)} t in 2030, mostly gas, fleet fuel and refrigerant leaks that still need a plan for net zero by ${p.assumptions.net_zero_year}.</li>`,
    ];
    if (worst.abated_vs_bau_t < 0) {
      items.push(`<li><b>${esc(label(worst.scenario))} on its own adds ${fmt(-worst.abated_vs_bau_t)} t</b>, because Victoria's grid power is still more carbon-heavy than burning gas for the same heat. It only helps alongside renewable electricity.</li>`);
    }
    $("path-finding").innerHTML = `<ul class="findings">${items.join("")}</ul>`;
  }

  // ---------------- hotspots ----------------
  function renderHotspots() {
    const s = D.summary.by_fy[state.fy], b = base(), surface = css("--surface");
    const src = [...s.sources].sort((a, c) => a.t - c.t);  // ascending: largest at top of a horizontal bar chart
    const bld = [...s.buildings].sort((a, c) => a.kg_per_m2 - c.kg_per_m2);
    const hi = s.buildings[0], lo = s.buildings[s.buildings.length - 1];
    $("h-hot").textContent = `${hi.name} emits ${fmt(hi.kg_per_m2)} kg CO2-e per m², ${fmt(hi.kg_per_m2 / lo.kg_per_m2, 1)} times the ${lo.name.replace(/ \(.*\)/, "")}`;
    const narrow = window.innerWidth < 520;
    const hbar = (cats, data, colors, unit, name) => ({
      textStyle: b.textStyle, grid: { left: narrow ? 112 : 168, right: 56, top: 8, bottom: 40, containLabel: false },
      tooltip: Object.assign({}, b.tooltip, { trigger: "item", formatter: (q) => `${esc(q.name)}<br><b>${fmt(q.value)}</b> ${unit}` }),
      xAxis: ax({ type: "value", name, nameLocation: "middle", nameGap: 26, splitNumber: narrow ? 3 : 5,
        axisLabel: { color: css("--ink-2"), hideOverlap: true, formatter: (v) => (v >= 1000 ? v / 1000 + "K" : v) } }),
      yAxis: ax({ type: "category", data: cats, axisLabel: { color: css("--ink"), lineHeight: 15, formatter: (v) => wrap(v, narrow ? 14 : 22) } }, { splitLine: { show: false } }),
      series: [{
        type: "bar", barMaxWidth: 20, data: data.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [0, 4, 4, 0] } })),
        label: { show: true, position: "right", color: css("--ink-2"), formatter: (q) => fmt(q.value) },
        itemStyle: { borderColor: surface, borderWidth: 1 },
      }],
    });
    chart("c-sources").setOption(hbar(src.map((r) => r.source), src.map((r) => r.t), src.map((r) => css("--s" + r.scope)), "t CO2-e", "t CO2-e"), true);
    chart("c-buildings").setOption(hbar(bld.map((r) => r.name), bld.map((r) => r.kg_per_m2), bld.map(() => css("--neutral-bar")), "kg CO2-e per m²", "kg CO2-e per m²"), true);
  }

  // ---------------- grid timing ----------------
  function renderGrid() {
    const g = D.grid, b = base();
    if (!g.available) {
      $("h-grid").textContent = `Each kWh from the grid adds ${g.fallback_intensity} kg CO2-e, whatever the time of day`;
      $("grid-finding").textContent = `The campus used ${fmt(D.summary.by_fy[state.fy].energy.grid_mwh)} MWh of grid electricity in ${state.fy}. ` +
        `This version uses Victoria's official yearly average for every hour, so using power at midday or at night counts the same. ` +
        `With half-hourly AEMO grid data added, this section shows when campus power is cleanest and how much shifting load would save.`;
      $("grid-source").textContent = "";
      $("c-grid").style.display = "none";
      document.querySelector(".grid-band .scale").style.display = "none";
      document.querySelector(".grid-band .dek").textContent = "How much carbon each unit of grid electricity carries in Victoria.";
      return;
    }
    const pct = 100 * (g.dirtiest_intensity / g.cleanest_intensity - 1);
    $("h-grid").textContent = `Victorian grid power is ${fmt(pct)}% dirtier at ${hh(g.dirtiest_hour)} than at ${hh(g.cleanest_hour)}`;
    $("hour-facts").innerHTML =
      `<div><b>${hh(g.cleanest_hour)}</b><span>cleanest hour, ${fmt(g.cleanest_intensity, 2)} kg per kWh</span></div>` +
      `<div><b>${hh(g.dirtiest_hour)}</b><span>dirtiest hour, ${fmt(g.dirtiest_intensity, 2)} kg per kWh</span></div>` +
      `<div><b>${fmt(g.load_shift_saved_t)} t</b><span>avoided a year by shifting 10% of peak-hour load</span></div>`;
    const data = [];
    let lo = Infinity, hi = -Infinity;
    g.values.forEach((row, y) => row.forEach((v, x) => { if (v != null) { data.push([x, y, v]); lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    $("scale-lo").textContent = fmt(lo, 2) + " cleaner";
    $("scale-hi").textContent = fmt(hi, 2) + " kg/kWh dirtier";
    chart("c-grid").setOption({
      textStyle: b.textStyle, grid: Object.assign({}, b.grid, { top: 8 }),
      tooltip: Object.assign({}, b.tooltip, {
        trigger: "item",
        formatter: (q) => `${monthLabel(g.months[q.value[1]], true)}, ${hh(q.value[0])}–${hh((q.value[0] + 1) % 24)}<br><b>${fmt(q.value[2], 3)}</b> kg CO2-e per kWh`,
      }),
      xAxis: ax({ type: "category", data: g.hours.map((h) => String(h).padStart(2, "0")), name: "Hour of day", nameLocation: "middle", nameGap: 26 }, { splitLine: { show: false }, axisLine: { show: false } }),
      yAxis: ax({ type: "category", data: g.months.map((m) => monthLabel(m) + " " + m.slice(2, 4)), inverse: true }, { splitLine: { show: false }, axisLine: { show: false } }),
      visualMap: { show: false, min: lo, max: hi, inRange: { color: ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4"].map(css) } },
      series: [{ type: "heatmap", data, itemStyle: { borderColor: css("--surface"), borderWidth: 1.5, borderRadius: 2 },
        emphasis: { itemStyle: { borderColor: css("--ink"), borderWidth: 1.5 } } }],
    }, true);
    $("grid-finding").textContent =
      `Moving 10% of the campus load in each day's three dirtiest hours to its three cleanest hours (${fmt(g.load_shift_mwh)} MWh a year) ` +
      `would avoid about ${fmt(g.load_shift_saved_t)} t CO2-e. Solar floods the grid around midday; evenings lean on brown coal and gas.`;
    $("grid-source").textContent = `Source: ${g.source}. Uses average grid intensity, so treat the saving as an indicator rather than an inventory figure.`;
  }

  // ---------------- data health ----------------
  function renderHealth() {
    const rows = D.health[state.fy];
    const avg = rows.reduce((a, r) => a + r.score, 0) / rows.length;
    const open = rows.reduce((a, r) => a + r.open_issues, 0), issues = rows.reduce((a, r) => a + r.issues, 0);
    $("h-health").textContent = issues
      ? `Data quality scored ${fmt(avg, 1)} out of 100 in ${state.fy}: ${issues} issue${issues > 1 ? "s" : ""} flagged, ${open} still open`
      : `All ${rows.length} data sources were complete, valid and on time in ${state.fy}`;
    const flaggedFys = D.summary.fys.filter((f) => D.health[f].some((r) => r.issues));
    $("health-hint").textContent = issues ? "" : (flaggedFys.length ? `Select ${flaggedFys.join(" or ")} above to see the problems the checks caught.` : "");
    const chip = (st) => `<span class="status ${st.toLowerCase()}"><span class="dot" aria-hidden="true"></span>${st}</span>`;
    $("health-body").innerHTML = rows.map((r, i) => {
      const det = r.flagged.length
        ? "<ul>" + r.flagged.map((f) => `<li><b>${esc(f.check)}</b> (${esc(f.entity)}, ${esc(f.period)}): ${esc(f.detail)}. <em>${esc(f.status)}</em></li>`).join("") + "</ul>"
        : "Nothing flagged: complete, valid and on time.";
      return `<tr class="src-row" data-i="${i}"><td><button type="button" aria-expanded="false" aria-controls="det-${i}">${esc(SOURCE_NAMES[r.source] || r.source)}</button></td>` +
        `<td><span class="owner">${esc(r.owner)}<br>${esc(r.role)}</span></td>` +
        `<td class="num">${fmt(r.completeness_pct, r.completeness_pct % 1 ? 1 : 0)}%</td><td class="num">${fmt(r.days_late)}</td>` +
        `<td class="num">${fmt(r.open_issues)}</td><td class="num">${fmt(r.score, 1)}</td><td>${chip(r.status)}</td></tr>` +
        `<tr class="detail" id="det-${i}" hidden><td colspan="7">${det}</td></tr>`;
    }).join("");
  }

  function renderAll() {
    renderKpis(); renderScope(); renderPathway(); renderHotspots(); renderGrid(); renderHealth();
  }

  // ---------------- controls ----------------
  function setupControls() {
    $("fy-select").innerHTML = D.summary.fys.map((f) => `<button type="button" data-fy="${f}" aria-pressed="${f === state.fy}">${f}</button>`).join("");
    $("fy-select").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-fy]"); if (!btn) return;
      state.fy = btn.dataset.fy;
      $("fy-select").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === btn));
      renderKpis(); renderScope(); renderHotspots(); renderHealth();
    });
    document.querySelector("[aria-label='How to count electricity']").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-method]"); if (!btn) return;
      state.method = btn.dataset.method;
      btn.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === btn));
      renderScope();
    });
    $("scenario-chips").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-scen]"); if (!btn) return;
      const s = btn.dataset.scen;
      state.scen.has(s) ? state.scen.delete(s) : state.scen.add(s);
      renderPathway();
    });
    $("health-body").addEventListener("click", (e) => {
      const tr = e.target.closest("tr.src-row"); if (!tr) return;
      const btn = tr.querySelector("button"), det = $("det-" + tr.dataset.i);
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", open); det.hidden = !open;
    });
    const isDark = () => document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const label = () => { $("theme-btn").textContent = isDark() ? "Light mode" : "Dark mode"; };
    $("theme-btn").addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("cct-theme", next); } catch (_) { /* storage unavailable: theme just won't persist */ }
      label(); renderAll();
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { label(); renderAll(); });
    label();
    let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => Object.values(charts).forEach((c) => c.resize()), 120); });
  }

  try { const t = localStorage.getItem("cct-theme"); if (t) document.documentElement.dataset.theme = t; } catch (_) { /* ignore */ }

  Promise.all(["summary", "pathway", "grid", "data_health"].map((n) => fetch(`data/${n}.json`).then((r) => {
    if (!r.ok) throw new Error(`data/${n}.json: HTTP ${r.status}`);
    return r.json();
  }))).then(([summary, pathway, grid, health]) => {
    D = { summary, pathway, grid, health };
    state.fy = summary.fys[summary.fys.length - 1];
    setupControls();
    renderAll();
  }).catch((err) => {
    const msg = typeof echarts === "undefined"
      ? "The chart library could not be loaded, so the charts are blank. Check your connection or any content blocker, then reload."
      : `The dashboard data could not be loaded (${esc(err.message)}). Run <code>python -m pipeline.run</code> and serve the docs/ folder.`;
    document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="panel">${msg}</p>`);
    console.error(err);
  });
})();
