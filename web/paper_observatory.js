(function () {
  "use strict";

  const state = {
    view: "dashboard",        // dashboard | aggregate | account | fund
    currentAccount: null,
    currentCategory: "",       // 论文总控筛选："" | 公众号 | 期刊
    currentPage: 1,
    aggPage: 1,
    pageSize: 10,
    totalPages: 1,
    accounts: [],
    categories: {},
    fetchPolling: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const navStack = $("#nav-stack");
  const metricStrip = $("#metric-strip");
  const topology = $("#topology");
  const dashboardCards = $("#dashboard-cards");
  const aggregateArticles = $("#aggregate-articles");
  const accountArticles = $("#account-articles");
  const pageTitle = $("#page-title");
  const pageEyebrow = $("#page-eyebrow");
  const snapshotTime = $("#snapshot-time");
  const serviceDot = $("#service-dot");
  const serviceState = $("#service-state");
  const fetchButton = $("#fetch-button");
  const fetchCustomButton = $("#fetch-custom-button");
  const fetchCustomPop = $("#custom-fetch-pop");
  const fetchCustomClose = $("#custom-fetch-close");
  const fetchCustomStart = $("#custom-fetch-start");
  const fetchCustomEnd = $("#custom-fetch-end");
  const fetchCustomConfirm = $("#custom-fetch-confirm");
  const toast = $("#toast");

  // ===== 工具函数 =====
  const API_BASE = (location.protocol === "file:") ? "http://127.0.0.1:8032" : "";
  function absUrl(u) {
    return (typeof u === "string" && u.startsWith("/")) ? API_BASE + u : u;
  }

  async function fetchJSON(url, options) {
    const resp = await fetch(absUrl(url), options);
    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status} ${body}`);
    }
    return resp.json();
  }

  function showToast(message, isError) {
    toast.textContent = message;
    toast.classList.toggle("is-error", !!isError);
    toast.classList.add("is-show");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove("is-show"), 3200);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function formatTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso.replace("Z", "+00:00"));
      return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    } catch (e) { return ""; }
  }

  function formatDateLabel(dateStr) {
    const p = dateStr.split(".");
    if (p.length === 3) return `${p[0]}年${Number(p[1])}月${Number(p[2])}日`;
    return dateStr;
  }

  function catClass(cat) {
    return cat === "期刊" ? "is-journal" : (cat === "基金" ? "is-fund" : "is-mp");
  }

  // ===== 健康检查 =====
  async function checkHealth() {
    try {
      await fetchJSON("/api/health");
      serviceDot.classList.add("is-live");
      serviceState.textContent = "服务正常";
    } catch (e) {
      serviceDot.classList.remove("is-live");
      serviceState.textContent = "连接失败";
    }
  }

  // ===== 总览 =====
  async function loadOverview() {
    try {
      const data = await fetchJSON("/api/overview");
      state.accounts = data.accounts || [];
      state.categories = data.categories || {};
      renderNav(state.accounts);
      renderMetrics(data);
      renderTopology(state.accounts);
      renderDashboard(state.categories);
      snapshotTime.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      showToast("加载总览失败：" + e.message, true);
    }
  }

  function renderNav(accounts) {
    const pub = accounts.filter((a) => a.category === "公众号");
    const jour = accounts.filter((a) => a.category === "期刊");

    const group = (label, cat, list) => `
      <div class="nav-group" data-group="${cat}">
        <button class="nav-item nav-group__header" data-group="${cat}" aria-expanded="true" type="button">
          <svg><use href="#i-paper"/></svg><span>${escapeHtml(label)}</span><b>${list.length}</b>
          <svg class="nav-group__chevron"><use href="#i-chevron"/></svg>
        </button>
        <div class="nav-group__children">
          ${list.map((a) => `
            <button class="nav-item nav-sub" data-account="${escapeHtml(a.name)}" data-view="account" type="button">
              <svg><use href="#i-paper"/></svg><span>${escapeHtml(a.name)}</span><b>${a.article_count}</b>
            </button>`).join("")}
        </div>
      </div>`;

    navStack.innerHTML = `
      <button class="nav-item is-active" data-view="dashboard" type="button">
        <svg><use href="#i-grid"/></svg><span>文件总控</span><b>HOME</b>
      </button>
      <button class="nav-item" data-view="aggregate" type="button">
        <svg><use href="#i-search"/></svg><span>论文总控</span><b>ALL</b>
      </button>
      ${group("公众号", "公众号", pub)}
      ${group("期刊", "期刊", jour)}
      <button class="nav-item" data-view="fund" type="button">
        <svg><use href="#i-fund"/></svg><span>基金</span><b>SOON</b>
      </button>`;

    navStack.querySelectorAll(".nav-group__header").forEach((h) => {
      h.addEventListener("click", () => {
        const g = h.closest(".nav-group");
        const collapsed = g.classList.toggle("is-collapsed");
        h.setAttribute("aria-expanded", String(!collapsed));
      });
    });
    navStack.querySelectorAll("[data-view]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.classList.contains("nav-group__header")) return;
        const view = btn.dataset.view;
        const acct = btn.dataset.account;
        if (acct) openAccount(acct);
        else showView(view);
      });
    });
  }

  function renderMetrics(data) {
    const lastDate = (data.accounts || [])
      .map((a) => a.last_date).filter(Boolean).sort().pop() || "—";
    metricStrip.innerHTML = `
      <div class="metric-cell"><span>信息源</span><strong>${data.total_accounts}</strong></div>
      <div class="metric-cell"><span>累计论文</span><strong>${data.total_articles}</strong></div>
      <div class="metric-cell"><span>归档天数</span><strong>${data.total_days}</strong></div>
      <div class="metric-cell is-alert"><span>最近归档</span><strong>${lastDate}</strong></div>`;
  }

  function renderTopology(accounts) {
    const pub = accounts.filter((a) => a.category === "公众号").length;
    const jour = accounts.filter((a) => a.category === "期刊").length;
    if (!accounts.length) {
      topology.innerHTML = '<div class="empty">暂无归档数据</div>';
      return;
    }
    const core = `
      <div class="topology-core">
        <span>SOURCES</span><strong>${accounts.length}</strong>
        <small>公众号 ${pub} · 期刊 ${jour}</small>
      </div>`;
    const top = accounts.slice(0, 8);
    const nodes = top.map((a) => `
      <div class="topology-node">
        <div><strong>${escapeHtml(a.name)}</strong><span>${a.day_count} 天 · ${a.article_count} 篇</span></div>
        <b>${a.article_count}</b>
      </div>`).join("");
    topology.innerHTML = core + nodes;
  }

  function renderDashboard(categories) {
    const pub = categories["公众号"] || { sources: 0, articles: 0, days: 0 };
    const jour = categories["期刊"] || { sources: 0, articles: 0, days: 0 };
    const card = (icon, title, sub, stat, desc, extraCls) => `
      <div class="dashboard-card ${extraCls || ""}">
        <div class="dashboard-card__head"><svg><use href="#${icon}"/></svg><span>${escapeHtml(sub)}</span></div>
        <h4>${escapeHtml(title)}</h4>
        <div class="dashboard-card__stats">
          <div><span>来源数</span><strong>${stat.sources}</strong></div>
          <div><span>累计论文</span><strong>${stat.articles}</strong></div>
          <div><span>归档天数</span><strong>${stat.days}</strong></div>
        </div>
        <p class="dashboard-card__desc">${escapeHtml(desc)}</p>
      </div>`;
    dashboardCards.innerHTML = `
      ${card("i-paper", "公众号", "WECHAT MP", pub, "微信读书订阅的 5 个环境/膜领域公众号，每日推文按账号归档。")}
      ${card("i-search", "期刊", "JOURNALS RSS", jour, "各出版商 RSS 直连抓取（Nature / arXiv / ScienceDirect / ACS 等），按期刊归档。")}
      <div class="dashboard-card is-fund">
        <div class="dashboard-card__head"><svg><use href="#i-fund"/></svg><span>FUNDS · 规划中</span></div>
        <h4>基金</h4>
        <div class="dashboard-card__stats">
          <div><span>申报通知</span><strong>—</strong></div>
          <div><span>结题项目</span><strong>—</strong></div>
          <div><span>状态</span><strong>占位</strong></div>
        </div>
        <p class="dashboard-card__desc">拟纳入基金申报通知与成熟/结题项目，待公众号、期刊两块稳定后设计。</p>
      </div>`;
  }

  // ===== 页面切换 =====
  function showView(view) {
    state.view = view;
    state.currentAccount = null;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    const page = document.querySelector(`.page[data-view="${view}"]`);
    if (page) page.classList.add("is-visible");
    setActiveNav(view);
    const meta = {
      dashboard: ["PAPER MAP / 00", "论文观察台"],
      aggregate: ["AGGREGATE / ALL", "论文总控"],
      fund: ["FUND / SOON", "基金模块"],
    }[view] || ["", ""];
    pageEyebrow.textContent = meta[0];
    pageTitle.textContent = meta[1];
    if (view === "aggregate") { state.aggPage = 1; loadAggregate(state.currentCategory, 1); }
  }

  function setActiveNav(key) {
    navStack.querySelectorAll(".nav-item").forEach((btn) => {
      const match = key && btn.dataset.view === key && !btn.dataset.account
        ? true
        : (key && btn.dataset.account === key ? true : false);
      btn.classList.toggle("is-active", match);
    });
  }

  async function openAccount(name) {
    state.view = "account";
    state.currentAccount = name;
    state.currentPage = 1;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    document.querySelector('.page[data-view="account"]').classList.add("is-visible");
    pageTitle.textContent = name;
    pageEyebrow.textContent = "ACCOUNT / ARCHIVE";
    const acc = state.accounts.find((a) => a.name === name);
    $("#account-page-title").textContent = name;
    $("#account-desc").textContent = acc
      ? `累计 ${acc.article_count} 篇 · ${acc.day_count} 个归档日 · 最近 ${acc.last_date || "—"}`
      : "按日期倒序回溯每篇内容。";
    setActiveNav(name);
    await loadAccountArticles(name, 1);
  }

  // ===== 文章渲染（聚合 / 单来源共用） =====
  function renderArticlesInto(container, pageEl, articles) {
    if (!articles || !articles.length) {
      container.innerHTML = `
        <div class="empty empty--large">
          <p>该范围暂无归档文章</p>
          <p class="empty-hint">可能原因：① 今天该源没发文 ② 出版商 RSS 在本环境被拦截（ScienceDirect / ACS / MDPI）</p>
          <p class="empty-hint">试试点右上角「现场抓取」，或确认网络可访问该出版商</p>
        </div>`;
      return;
    }
    const groups = {};
    articles.forEach((a) => {
      const d = a.date || "未知";
      (groups[d] = groups[d] || []).push(a);
    });
    container.innerHTML = Object.entries(groups).map(([date, list]) => `
      <div class="date-group">
        <div class="date-group__head"><span class="dot"></span><h3>${formatDateLabel(date)}</h3><span>${list.length} 篇</span></div>
        ${list.map((a) => `
          <div class="article-row" data-article='${escapeHtml(JSON.stringify(a))}'>
            <div class="article-row__time">${formatTime(a.date_published)}</div>
            <div class="article-row__main">
              <h4>${escapeHtml(a.title)}</h4>
              <p class="article-row__subtitle">${escapeHtml(a.title_zh || a.summary || "")}</p>
            </div>
            <span class="cat-badge ${catClass(a.category)}">${escapeHtml(a.category || "公众号")}</span>
            <div class="article-row__arrow"><svg><use href="#i-arrow"/></svg></div>
          </div>`).join("")}
      </div>`).join("");
    if (pageEl) pageEl.classList.add("is-visible");
    container.querySelectorAll(".article-row").forEach((row) => {
      row.addEventListener("click", () => {
        try { openDrawer(JSON.parse(row.dataset.article)); }
        catch (e) { openDrawer({ title: "文章", url: "#" }); }
      });
    });
  }

  function setupPagination(prevBtn, nextBtn, infoEl, page, totalPages, onPage) {
    prevBtn.disabled = page <= 1;
    nextBtn.disabled = page >= totalPages;
    infoEl.textContent = `${page} / ${totalPages}`;
    prevBtn.onclick = () => { if (page > 1) onPage(page - 1); };
    nextBtn.onclick = () => { if (page < totalPages) onPage(page + 1); };
  }

  // ===== 单来源归档 =====
  async function loadAccountArticles(name, page) {
    try {
      const data = await fetchJSON(`/api/articles?account=${encodeURIComponent(name)}&page=${page}&size=${state.pageSize}`);
      state.totalPages = data.total_pages || 1;
      renderArticlesInto(accountArticles, null, data.articles || []);
      setupPagination($("#page-prev"), $("#page-next"), $("#page-info"), page, data.total_pages || 1,
        (p) => { state.currentPage = p; loadAccountArticles(name, p); });
    } catch (e) {
      showToast("加载文章失败：" + e.message, true);
      accountArticles.innerHTML = `<div class="empty empty--large"><p>加载失败</p><p class="empty-hint">${escapeHtml(e.message)}</p></div>`;
    }
  }

  // ===== 论文总控（聚合） =====
  async function loadAggregate(category, page) {
    try {
      const q = category ? `&category=${encodeURIComponent(category)}` : "";
      const data = await fetchJSON(`/api/articles?page=${page}&size=${state.pageSize}${q}`);
      state.totalPages = data.total_pages || 1;
      renderArticlesInto(aggregateArticles, null, data.articles || []);
      setupPagination($("#agg-page-prev"), $("#agg-page-next"), $("#agg-page-info"), page, data.total_pages || 1,
        (p) => { state.aggPage = p; loadAggregate(category, p); });
    } catch (e) {
      showToast("加载聚合失败：" + e.message, true);
      aggregateArticles.innerHTML = `<div class="empty empty--large"><p>加载失败</p><p class="empty-hint">${escapeHtml(e.message)}</p></div>`;
    }
  }

  // ===== 抽屉 =====
  const drawer = $("#detail-drawer");
  const drawerBackdrop = $("#drawer-backdrop");

  function openDrawer(article) {
    $("#drawer-title").textContent = article.account || "文章";
    $("#drawer-purpose").textContent = article.date ? formatDateLabel(article.date) : "";
    $("#drawer-stats").innerHTML = `
      <div class="drawer-stat"><span>来源</span><strong>${escapeHtml(article.account || "—")}</strong></div>
      <div class="drawer-stat"><span>分类</span><strong>${escapeHtml(article.category || "公众号")}</strong></div>
      <div class="drawer-stat"><span>发布时间</span><strong>${formatTime(article.date_published) || "—"}</strong></div>`;
    $("#article-full-title").textContent = article.title || "";
    $("#article-full-subtitle").textContent = article.title_zh || "";
    $("#article-full-subtitle").style.display = article.title_zh ? "" : "none";
    $("#article-full-meta").innerHTML = `
      <span><svg><use href="#i-clock"/></svg>${escapeHtml(article.date_published || "")}</span>
      <span><svg><use href="#i-calendar"/></svg>${escapeHtml(article.date || "")}</span>
      <span><svg><use href="#i-paper"/></svg>${escapeHtml(article.category || "公众号")}</span>`;
    $("#article-full-summary").textContent = article.summary || "（无摘要，请点击下方按钮查看原文）";
    const link = $("#article-full-link");
    link.href = article.url || "#";
    link.style.display = article.url ? "" : "none";
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    drawerBackdrop.hidden = false;
    requestAnimationFrame(() => drawerBackdrop.classList.add("is-open"));
  }

  function closeDrawer() {
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    drawerBackdrop.classList.remove("is-open");
    setTimeout(() => { drawerBackdrop.hidden = true; }, 260);
  }
  $("#drawer-close").addEventListener("click", closeDrawer);
  drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  // ===== 现场抓取 =====
  async function triggerFetch() {
    if (fetchButton.disabled) return;
    fetchButton.disabled = true;
    fetchButton.classList.add("is-running");
    fetchButton.querySelector("span").textContent = "抓取中…";
    try {
      await fetchJSON("/api/fetch", { method: "POST" });
      showToast("现场抓取已启动，正在后台运行…");
      pollFetchStatus();
    } catch (e) {
      showToast("启动抓取失败：" + e.message, true);
      resetFetchButton();
    }
  }

  function pollFetchStatus() {
    clearInterval(state.fetchPolling);
    state.fetchPolling = setInterval(async () => {
      try {
        const s = await fetchJSON("/api/fetch/status");
        if (!s.running) {
          clearInterval(state.fetchPolling);
          resetFetchButton();
          if (s.code === 0) {
            showToast("抓取完成，已更新归档");
            snapshotTime.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
            loadOverview();
            if (state.view === "account" && state.currentAccount) loadAccountArticles(state.currentAccount, 1);
            if (state.view === "aggregate") loadAggregate(state.currentCategory, state.aggPage);
          } else {
            showToast("抓取失败，详见后端日志", true);
          }
        }
      } catch (e) {
        clearInterval(state.fetchPolling);
        resetFetchButton();
        showToast("状态查询失败：" + e.message, true);
      }
    }, 1500);
  }

  function resetFetchButton() {
    fetchButton.disabled = false;
    fetchButton.classList.remove("is-running");
    fetchButton.querySelector("span").textContent = "现场抓取";
  }
  fetchButton.addEventListener("click", triggerFetch);

  // ===== 自定义抓取 =====
  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function openCustomFetch() {
    const t = todayStr();
    if (!fetchCustomStart.value) fetchCustomStart.value = t;
    if (!fetchCustomEnd.value) fetchCustomEnd.value = t;
    fetchCustomPop.hidden = false;
    fetchCustomStart.focus();
  }
  function closeCustomFetch() { fetchCustomPop.hidden = true; }
  fetchCustomButton.addEventListener("click", openCustomFetch);
  fetchCustomClose.addEventListener("click", closeCustomFetch);
  fetchCustomPop.addEventListener("click", (e) => { if (e.target === fetchCustomPop) closeCustomFetch(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCustomFetch(); });

  async function triggerCustomFetch() {
    let startDate = fetchCustomStart.value;
    let endDate = fetchCustomEnd.value;
    if (!startDate || !endDate) { showToast("请选择起始和结束日期", true); return; }
    if (startDate > endDate) { const t = startDate; startDate = endDate; endDate = t; }
    fetchCustomConfirm.disabled = true;
    fetchCustomConfirm.classList.add("is-running");
    try {
      await fetchJSON("/api/fetch-custom", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      showToast(`自定义抓取已启动：${startDate} ~ ${endDate}`);
      closeCustomFetch();
      pollFetchStatus();
    } catch (e) {
      showToast("启动抓取失败：" + e.message, true);
    } finally {
      fetchCustomConfirm.disabled = false;
      fetchCustomConfirm.classList.remove("is-running");
      fetchCustomConfirm.querySelector("span").textContent = "开始抓取";
    }
  }
  fetchCustomConfirm.addEventListener("click", triggerCustomFetch);

  // ===== 聚合筛选 chips =====
  $("#filter-chips").querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $("#filter-chips").querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      state.currentCategory = chip.dataset.cat || "";
      state.aggPage = 1;
      loadAggregate(state.currentCategory, 1);
    });
  });

  // ===== 启动 =====
  checkHealth();
  loadOverview();
})();
