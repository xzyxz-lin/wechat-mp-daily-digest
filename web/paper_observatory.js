(function () {
  "use strict";

  const state = {
    view: "dashboard",        // dashboard | aggregate | account | fund | favorites
    currentAccount: null,
    currentCategory: "",       // 论文总控筛选："" | 公众号 | 期刊
    currentPage: 1,
    aggPage: 1,
    pageSize: 10,
    totalPages: 1,
    accounts: [],
    categories: {},
    fetchPolling: null,
    fundKeywords: [],
    fundData: null,
    fundKw: "",
    fundQ: "",
    favCat: "公众号",          // 私人珍藏当前标签
    trashCategory: "",         // 回收站分类：全部 | 公众号 | 期刊 | 基金项目
    // 多选 / 批量删除
    selArticles: new Set(),   // 已选文章 id
    selFunds: new Set(),      // 已选基金 id
    selFav: new Set(),        // 私人珍藏中已选（值为 getFavId）
    lastAnchorArticle: null,  // Shift 范围选锚点
    lastAnchorFund: null,
    lastAnchorFav: null,
    continuousSelection: false, // 连续删除模式：普通点击按 Ctrl/Cmd 多选处理
    selectedItems: {
      article: new Map(),       // 已选文章的完整数据，用于删除前收藏保护
      fund: new Map(),
      fav: new Map(),
    },
  };

  // 卡片留白区用于整项操作；以下文字区保留浏览器原生的拖拽选字能力。
  const ROW_TEXT_SELECTOR = ".article-row__time, .article-row__main, .cat-badge, .fund-row__main, .fund-row__stat";

  const $ = (sel) => document.querySelector(sel);
  const navStack = $("#nav-stack");
  const metricStrip = $("#metric-strip");
  const topology = $("#topology");
  const dashboardCards = $("#dashboard-cards");
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
    return cat === "期刊" ? "is-journal" : ((cat === "基金" || cat === "基金项目") ? "is-fund" : "is-mp");
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
      // 拉取基金统计，填充总控卡片 + 导航计数
      try {
        const funds = await fetchJSON("/api/funds");
        state.fundKeywords = funds.keywords || [];
        updateFundDashboard(funds);
      } catch (e) { /* 无基金数据时不报错 */ }
      // 更新收藏计数
      try { updateFavCounts(); const fav = loadFavorites(); const navFavTotal = document.getElementById("nav-fav-total"); if (navFavTotal) navFavTotal.textContent = fav.mp.length + fav.journal.length + fav.fund.length; } catch(e){}
      // 更新回收站导航计数；失败时不影响主页面加载。
      try { await loadTrashSummary(); } catch (e) {}
      // 加载每日快照
      loadSnapshot();
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
      <button class="nav-item" data-view="favorites" type="button">
        <svg><use href="#i-star"/></svg><span>私人珍藏</span><b id="nav-fav-total">0</b>
      </button>
      ${group("公众号", "公众号", pub)}
      ${group("期刊", "期刊", jour)}
      <button class="nav-item" data-view="fund" type="button">
        <svg><use href="#i-fund"/></svg><span>基金</span><b id="nav-fund-count"></b>
      </button>
      <button class="nav-item" data-view="trash" type="button">
        <svg><use href="#i-trash"/></svg><span>回收站</span><b id="nav-trash-count">0</b>
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
    const card = (icon, title, sub, stat, desc, extraCls, jumpCat) => `
      <div class="dashboard-card ${extraCls || ""}" data-jump="${jumpCat || ""}">
        <div class="dashboard-card__head"><svg><use href="#${icon}"/></svg><span>${escapeHtml(sub)}</span></div>
        <h4>${escapeHtml(title)}</h4>
        <div class="dashboard-card__stats">
          <div><span>来源数</span><strong>${stat.sources}</strong></div>
          <div><span>累计论文</span><strong>${stat.articles}</strong></div>
          <div><span>归档天数</span><strong>${stat.days}</strong></div>
        </div>
        <p class="dashboard-card__desc">${escapeHtml(desc)}</p>
        <div class="dashboard-card__action">点击查看详情 →</div>
      </div>`;
    dashboardCards.innerHTML = `
      ${card("i-paper", "公众号", "WECHAT MP", pub, "微信读书订阅的 5 个环境/膜领域公众号，每日推文按账号归档。", "", "公众号")}
      ${card("i-search", "期刊", "JOURNALS RSS", jour, "各出版商 RSS 直连抓取（Nature / arXiv / ScienceDirect / ACS 等），按期刊归档。", "", "期刊")}
      <div class="dashboard-card is-fund" data-jump="基金">
        <div class="dashboard-card__head"><svg><use href="#i-fund"/></svg><span>FUNDS · 国自然</span></div>
        <h4>基金（结题 + 论文）</h4>
        <div class="dashboard-card__stats">
          <div><span>结题项目</span><strong id="fund-card-projects">—</strong></div>
          <div><span>成果论文</span><strong id="fund-card-papers">—</strong></div>
          <div><span>关键词</span><strong>${state.fundKeywords ? state.fundKeywords.length : 0}</strong></div>
        </div>
        <p class="dashboard-card__desc">国自然结题项目 + 其成果论文，按膜/反渗透/膜污染清洗/CFD 等方向精筛。手动抓取（fetch_funds.py）。</p>
        <div class="dashboard-card__action">点击查看详情 →</div>
      </div>`;

    // 卡片点击跳转：展开对应导航分组并高亮第一个子项
    dashboardCards.querySelectorAll(".dashboard-card[data-jump]").forEach((cardEl) => {
      cardEl.style.cursor = "pointer";
      cardEl.addEventListener("click", () => {
        const cat = cardEl.dataset.jump;
        if (!cat) return;
        if (cat === "基金") { showView("fund"); return; }
        // 展开对应导航分组
        const group = navStack.querySelector(`.nav-group[data-group="${cat}"]`);
        if (group) {
          group.classList.remove("is-collapsed");
          const header = group.querySelector(".nav-group__header");
          if (header) header.setAttribute("aria-expanded", "true");
          // 高亮分组标题
          navStack.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("is-active"));
          header.classList.add("is-active");
          // 点击第一个子项（打开第一个来源）
          const firstSub = group.querySelector(".nav-sub");
          if (firstSub) firstSub.click();
        }
      });
    });
  }

  // ===== 页面切换 =====
  let _fundLoaded = false;
  function showView(view) {
    state.view = view;
    state.currentAccount = null;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    const page = document.querySelector(`.page[data-view="${view}"]`);
    if (page) page.classList.add("is-visible");
    setActiveNav(view);
    const meta = {
      dashboard: ["PAPER MAP / 00", "论文观察台"],
      fund: ["FUND / NSFC", "国自然基金观察"],
    }[view] || ["", ""];
    pageEyebrow.textContent = meta[0];
    pageTitle.textContent = meta[1];
    if (view === "fund") {
      loadFunds(state.fundKw, state.fundQ);
    }
  }

  function setActiveNav(key) {
    navStack.querySelectorAll(".nav-item").forEach((btn) => {
      const match = key && btn.dataset.view === key && !btn.dataset.account
        ? true
        : (key && btn.dataset.account === key ? true : false);
      btn.classList.toggle("is-active", match);
    });
    // 更新收藏总数
    if (key === "favorites") {
      try { const fav = loadFavorites(); const el = document.getElementById("nav-fav-total"); if (el) el.textContent = fav.mp.length + fav.journal.length + fav.fund.length; } catch(e){}
    }
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
          <div class="article-row" data-article='${escapeHtml(JSON.stringify(a))}' data-sel-id='${escapeHtml(String(a.id))}' data-sel-kind="article">
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
      row.addEventListener("click", (e) => handleRowClick(row, e));
      row.addEventListener("dblclick", () => handleRowDblClick(row));
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
    if (page === 1) clearSelection();   // 进入新列表时清空选择
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

  // ===== 基金模块 =====
  const fundsFetchButton = $("#funds-fetch-button");
  const fundsFetchText = $("#funds-fetch-text");
  const fundsFetchStatus = $("#funds-fetch-status");
  let fundsFetchPolling = null;

  function updateFundDashboard(funds) {
    const pc = document.getElementById("fund-card-projects");
    const pp = document.getElementById("fund-card-papers");
    const navc = document.getElementById("nav-fund-count");
    if (pc) pc.textContent = funds.completion_count || 0;
    if (pp) pp.textContent = funds.papers_total || 0;
    if (navc) navc.textContent = funds.total || 0;
  }

  // 基金一键抓取
  async function triggerFundsFetch() {
    if (fundsFetchButton.disabled) return;
    fundsFetchButton.disabled = true;
    fundsFetchButton.classList.add("is-running");
    fundsFetchText.textContent = "抓取中…";
    try {
      await fetchJSON("/api/funds/fetch", { method: "POST" });
      showToast("国自然基金抓取已启动，正在后台运行…");
      pollFundsFetchStatus();
    } catch (e) {
      showToast("启动基金抓取失败：" + e.message, true);
      resetFundsFetchButton();
    }
  }

  function pollFundsFetchStatus() {
    clearInterval(fundsFetchPolling);
    fundsFetchPolling = setInterval(async () => {
      try {
        const s = await fetchJSON("/api/funds/fetch/status");
        if (!s.running) {
          clearInterval(fundsFetchPolling);
          resetFundsFetchButton();
          if (s.code === 0) {
            showToast("基金数据抓取完成！");
            fundsFetchStatus.textContent = "✓ " + new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) + " 完成";
            loadFunds(state.fundKw, state.fundQ); // 刷新列表
            // 同时刷新总控卡片
            try { const fd = await fetchJSON("/api/funds"); updateFundDashboard(fd); } catch(e){}
          } else {
            showToast("基金抓取失败，详见后端日志", true);
            fundsFetchStatus.textContent = "✗ 失败";
          }
        }
      } catch (e) {
        clearInterval(fundsFetchPolling);
        resetFundsFetchButton();
      }
    }, 2000);
  }

  function resetFundsFetchButton() {
    fundsFetchButton.disabled = false;
    fundsFetchButton.classList.remove("is-running");
    fundsFetchText.textContent = "抓取基金数据";
  }

  fundsFetchButton.addEventListener("click", triggerFundsFetch);

  const fundList = $("#fund-list");
  const fundFilters = $("#fund-filters");
  const fundSearchInput = $("#fund-search-input");

  async function loadFunds(kw, q) {
    state.fundKw = kw || "";
    state.fundQ = q || "";
    let url = "/api/funds";
    const params = [];
    if (kw) params.push("kw=" + encodeURIComponent(kw));
    if (q) params.push("q=" + encodeURIComponent(q));
    if (params.length) url += "?" + params.join("&");
    try {
      const data = await fetchJSON(url);
      state.fundData = data;
      renderFundFilters(data.keywords || [], kw);
      renderFundList(data.funds || [], data);
    } catch (e) {
      fundList.innerHTML = `<div class="empty empty--large"><p>加载基金数据失败</p><p class="empty-hint">${escapeHtml(e.message)}</p><p class="empty-hint">请先运行 scripts/fetch_funds.py 抓取国自然结题数据。</p></div>`;
    }
  }

  function renderFundFilters(keywords, activeKw) {
    const chips = [`<button class="chip ${!activeKw ? "is-active" : ""}" data-kw="">全部</button>`]
      .concat(keywords.map((k) => `<button class="chip ${k === activeKw ? "is-active" : ""}" data-kw="${escapeHtml(k)}">${escapeHtml(k)}</button>`));
    fundFilters.innerHTML = chips.join("");
    fundFilters.querySelectorAll(".chip").forEach((c) => {
      c.addEventListener("click", () => loadFunds(c.dataset.kw || "", state.fundQ));
    });
  }

  function renderFundList(funds, data) {
    if (!funds.length) {
      fundList.innerHTML = `<div class="empty empty--large"><p>当前筛选条件下暂无基金数据</p><p class="empty-hint">可切换关键词或清空搜索；如从未抓取，请运行 fetch_funds.py。</p></div>`;
      return;
    }
    const note = data && data.support_note
      ? `<p class="fund-note">${escapeHtml(data.support_note)}</p>` : "";
    const srcLine = data && data.source
      ? `<p class="fund-source">数据源：${escapeHtml(data.source)} ｜ 生成时间：${escapeHtml((data.generated_at || "").slice(0, 19).replace("T", " "))}</p>` : "";
    fundList.innerHTML = note + srcLine + funds.map((f) => `
      <div class="fund-row" data-fund='${escapeHtml(JSON.stringify(f))}' data-sel-id='${escapeHtml(String(f.id))}' data-sel-kind="fund">
        <div class="fund-row__main">
          <h4>${escapeHtml(f.project_name || "（无标题）")}</h4>
          <p class="fund-row__meta">
            <span>${escapeHtml(f.project_type || "")}</span>
            <span>${escapeHtml(f.project_admin || "")} · ${escapeHtml(f.depend_unit || "")}</span>
            <span>批准号 ${escapeHtml(f.ratify_no || "")}</span>
            <span>${escapeHtml(f.ratify_year || "")}→结题 ${escapeHtml(f.conclusion_year || "")}</span>
            <span>${escapeHtml(f.support_num || "")} 万</span>
          </p>
          <p class="fund-row__kw">${escapeHtml(f.keywords || f.keywords_c || "")}</p>
        </div>
        <div class="fund-row__stat">
          <span class="fund-row__papers">${Array.isArray(f.papers) ? f.papers.length : (f.paper_count || 0)}<small>篇论文</small></span>
        </div>
        <div class="article-row__arrow"><svg><use href="#i-arrow"/></svg></div>
      </div>`).join("");
    fundList.querySelectorAll(".fund-row").forEach((row) => {
      row.addEventListener("click", (e) => handleRowClick(row, e));
      row.addEventListener("dblclick", () => handleRowDblClick(row));
    });
  }

  // 基金详情抽屉
  const fundDrawer = $("#fund-drawer");
  const fundDrawerBackdrop = $("#fund-drawer-backdrop");

  function openFundDrawer(fund) {
    $("#fund-drawer-title").textContent = fund.project_type || "基金项目";
    $("#fund-drawer-purpose").textContent = (fund.ratify_no || "") + (fund.conclusion_year ? ` · ${fund.conclusion_year} 结题` : "");
    $("#fund-drawer-stats").innerHTML = `
      <div class="drawer-stat"><span>负责人</span><strong>${escapeHtml(fund.project_admin || "—")}</strong></div>
      <div class="drawer-stat"><span>依托单位</span><strong>${escapeHtml(fund.depend_unit || "—")}</strong></div>
      <div class="drawer-stat"><span>批准年度</span><strong>${escapeHtml(fund.ratify_year || "—")}</strong></div>
      <div class="drawer-stat"><span>金额</span><strong>${escapeHtml(fund.support_num || "—")} 万</strong></div>
      <div class="drawer-stat"><span>申请代码</span><strong>${escapeHtml(fund.code || "—")}</strong></div>`;
    $("#fund-drawer-name").textContent = fund.project_name || "";
    $("#fund-drawer-meta").innerHTML = `
      <span><svg><use href="#i-paper"/></svg>${escapeHtml(fund.project_type || "")}</span>
      <span><svg><use href="#i-calendar"/></svg>结题 ${escapeHtml(fund.conclusion_year || "—")}</span>
      <span><svg><use href="#i-clock"/></svg>研究周期 ${escapeHtml(fund.research_scope || "—")}</span>`;
    $("#fund-drawer-abstract").textContent = fund.abstract_c || fund.conclusion_abstract || "（无摘要）";
    const papers = fund.papers || [];
    $("#fund-paper-count").textContent = papers.length;
    $("#fund-paper-list").innerHTML = papers.length
      ? papers.map((p) => `
        <li>
          <span class="ptype">${escapeHtml(p.type || "成果")}</span>
          <span class="ptitle">${escapeHtml(p.title || "")}</span>
          ${p.title_zh ? `<span class="ptitle-zh">${escapeHtml(p.title_zh)}</span>` : ""}
          <span class="pauthors">${escapeHtml(p.authors || "")}</span>
        </li>`).join("")
      : `<li class="empty-hint">该项目未列出成果论文</li>`;
    fundDrawer.classList.add("is-open");
    fundDrawer.setAttribute("aria-hidden", "false");
    fundDrawerBackdrop.hidden = false;
    requestAnimationFrame(() => fundDrawerBackdrop.classList.add("is-open"));
  }

  function closeFundDrawer() {
    fundDrawer.classList.remove("is-open");
    fundDrawer.setAttribute("aria-hidden", "true");
    fundDrawerBackdrop.classList.remove("is-open");
    setTimeout(() => { fundDrawerBackdrop.hidden = true; }, 260);
  }
  $("#fund-drawer-close").addEventListener("click", closeFundDrawer);
  fundDrawerBackdrop.addEventListener("click", closeFundDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeFundDrawer(); });

  // 基金论文标题翻译
  const fundTranslateBtn = $("#fund-translate-btn");
  fundTranslateBtn.addEventListener("click", async () => {
    fundTranslateBtn.disabled = true;
    fundTranslateBtn.textContent = "翻译中…";
    try {
      const r = await fetchJSON("/api/funds/translate");
      if (r.ok) {
        showToast(r.message || `已翻译 ${r.translated} 篇`);
        // 刷新当前抽屉的论文列表
        if (state.fundData) {
          const currentFundId = $("#fund-drawer-name").textContent;
          const fund = (state.fundData.funds || []).find(f => f.project_name === currentFundId);
          if (fund) openFundDrawer(fund);
        }
      } else {
        showToast(r.error || "翻译失败", true);
      }
    } catch (e) {
      showToast("翻译请求失败：" + e.message, true);
    } finally {
      fundTranslateBtn.disabled = false;
      fundTranslateBtn.textContent = "翻译标题";
    }
  });

  // 基金搜索（防抖）
  let fundSearchTimer = null;
  fundSearchInput.addEventListener("input", () => {
    clearTimeout(fundSearchTimer);
    const v = fundSearchInput.value.trim();
    fundSearchTimer = setTimeout(() => loadFunds(state.fundKw, v), 300);
  });

  // 进入基金视图时加载列表（防抖避免重复请求）

  // ===== 获批/资助查询（iframe 嵌入官方页面） =====
  // 验证码在 kd.nsfc.cn 官方页面中原生加载，无需代理
  const nsfcIframe = $("#nsfc-iframe");
  if (nsfcIframe) {
    nsfcIframe.addEventListener("load", () => {
      nsfcIframe.style.background = "#fff";
    });
    nsfcIframe.addEventListener("error", () => {
      nsfcIframe.style.background = "var(--paper-50)";
      nsfcIframe.insertAdjacentHTML("afterend",
        '<p style="padding:20px;text-align:center;color:var(--ink-700);">iframe 加载失败，请<a href="https://kd.nsfc.cn/#/fundingInit" target="_blank" rel="noopener">点击这里在新标签页打开</a></p>');
    });
  }

  // ===== /获批查询结束 =====

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
        if (s.running) {
          updateFetchProgress(s.output);
          return;
        }
        if (!s.running) {
          clearInterval(state.fetchPolling);
          resetFetchButton();
          if (s.code === 0) {
            const hasWarnings = (s.output || "").includes("[warning]");
            showToast(hasWarnings ? "抓取完成，但部分来源失败，请查看按钮提示" : "抓取完成，已更新归档", hasWarnings);
            fetchButton.title = hasWarnings ? (s.output || "").split(/\r?\n/).filter(line => line.includes("[warning]")).join("\n") : "";
            snapshotTime.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
            loadOverview();
            loadSnapshot();
            if (state.view === "account" && state.currentAccount) loadAccountArticles(state.currentAccount, 1);
          } else if (s.code === 2 && (s.output || "").includes("[locked]")) {
            showToast("已有另一项抓取在运行，本次没有重复执行", true);
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

  function updateFetchProgress(output) {
    const lines = (output || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const latest = lines.at(-1) || "";
    let label = "抓取中…";
    if (latest.startsWith("[journals] 正在抓取：")) {
      label = "抓取中 · " + latest.slice("[journals] 正在抓取：".length);
    } else if (latest.startsWith("[fetch] 刷新公众号源：")) {
      label = "刷新中 · " + latest.slice("[fetch] 刷新公众号源：".length).replace(/ \.\.\.$/, "");
    } else if (latest.startsWith("[fetch] 调用")) {
      label = "抓取中 · 公众号源";
    } else if (latest.startsWith("[2/4]")) {
      label = "抓取中 · 渲染中";
    } else if (latest.startsWith("[3/4]")) {
      label = "抓取中 · 保存中";
    } else if (latest.startsWith("[4/4]")) {
      label = "抓取中 · 发送中";
    }
    fetchButton.querySelector("span").textContent = label;
    fetchButton.title = latest;
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

  // ===== 收藏系统（私人珍藏） =====
  const FAV_KEY = "paper_obs_favorites";
  const SWIPE_THRESHOLD = 80; // 右滑超过 80px 触发收藏
  const STAR_HTML = `<span class="fav-star" aria-label="已收藏">★</span>`;
  // 全局滑动抑制时间戳：每次鼠标/触摸按下时更新，
  // click / dblclick 处理器通过它判断最近是否有拖动操作
  let _suppressClickUntil = 0;

  function loadFavorites() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || '{"mp":[],"journal":[],"fund":[]}'); }
    catch { return { mp: [], journal: [], fund: [] }; }
  }

  function saveFavorites(fav) {
    localStorage.setItem(FAV_KEY, JSON.stringify(fav));
  }

  function getFavId(item, cat) {
    /* 生成唯一 ID：公众号/期刊用 account+date+title 哈希，基金用 ratify_no */
    if (cat === "fund" || cat === "基金") return "f_" + (item.ratify_no || item.project_name || "");
    return (item.account || "") + "_" + (item.date || "") + "_" + (item.title || "");
  }

  function isFavorited(item, cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const id = getFavId(item, cat);
    return fav[key].some(f => getFavId(f, cat) === id);
  }

  function favoriteIdentityCandidates(item, kind) {
    const isFund = kind === "fund" || Boolean(item.ratify_no || item.project_name);
    if (!isFund) return new Set([getFavId(item, "公众号")]);
    // 同时识别新基金 ID 和早期中文分类下的旧 ID，避免旧收藏遗漏保护。
    return new Set([
      getFavId(item, "基金"),
      (item.account || "") + "_" + (item.date || "") + "_" + (item.title || ""),
    ]);
  }

  function isFavoritedAnywhere(item, kind) {
    // 兼容早期版本把单来源期刊写入错误收藏分组的情况；删除保护不能依赖当前页面分类。
    const fav = loadFavorites();
    const candidateIds = favoriteIdentityCandidates(item, kind);
    return [fav.mp || [], fav.journal || [], fav.fund || []].some(items => items.some(saved =>
      Array.from(favoriteIdentityCandidates(saved)).some(id => candidateIds.has(id))
    ));
  }

  function addFavorite(item, cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const id = getFavId(item, cat);
    if (fav[key].some(f => getFavId(f, cat) === id)) return false; // 已收藏
    fav[key].push({ ...item, _favAt: new Date().toISOString() });
    saveFavorites(fav);
    updateFavCounts();
    return true;
  }

  function removeFavorite(item, cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const id = getFavId(item, cat);
    const idx = fav[key].findIndex(f => getFavId(f, cat) === id);
    if (idx < 0) return false; // 未收藏
    fav[key].splice(idx, 1);
    saveFavorites(fav);
    updateFavCounts();
    return true;
  }

  // toggleFavorite 保留给其他场景（如点击星标按钮）
  function toggleFavorite(item, cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const id = getFavId(item, cat);
    const idx = fav[key].findIndex(f => getFavId(f, cat) === id);
    if (idx >= 0) {
      fav[key].splice(idx, 1);
      showToast("已取消收藏");
    } else {
      fav[key].push({ ...item, _favAt: new Date().toISOString() });
      showToast("★ 已加入私人珍藏");
    }
    saveFavorites(fav);
    updateFavCounts();
    return idx < 0;
  }

  function updateFavCounts() {
    const fav = loadFavorites();
    const el = (id) => document.getElementById(id);
    if (el("fav-mp-count")) el("fav-mp-count").textContent = fav.mp.length;
    if (el("fav-journal-count")) el("fav-journal-count").textContent = fav.journal.length;
    if (el("fav-fund-count")) el("fav-fund-count").textContent = fav.fund.length;
  }

  // 右滑标记：绑定到 article-row 和 fund-row
  function setupSwipeMark(containerSelector, rowSelector, cat) {
    let startX = 0, startY = 0, currentX = 0, dragging = false, row = null;
    let didSwipe = false;  // 标记是否发生了有效滑动（用于阻止 click 弹抽屉）

    function onDown(e) {
      // 鼠标从文字区域开始拖拽时，优先按普通文本选择处理，
      // 不把它误认为横向滑动收藏。
      if (!e.touches && e.target.closest(ROW_TEXT_SELECTOR)) return;
      row = e.target.closest(rowSelector);
      if (!row) return;
      dragging = true;
      didSwipe = false;
      startX = e.touches ? e.touches[0].clientX : e.clientX;
      startY = e.touches ? e.touches[0].clientY : e.clientY;
      currentX = startX;
      row.style.transition = "none";
      row._swiping = true;  // 标记正在拖动
    }

    function onMove(e) {
      if (!dragging || !row) return;
      currentX = e.touches ? e.touches[0].clientX : e.clientX;
      const dx = currentX - startX;
      const dy = Math.abs((e.touches ? e.touches[0].clientY : e.clientY) - startY);
      if (dy > 30) { dragging = false; row.style.transform = ""; row.style.transition = ""; row._swiping = false; return; } // 纵向滚动优先
      if (Math.abs(dx) > 2) didSwipe = true;  // 移动超过 2px 就算拖动
      if (didSwipe) _suppressClickUntil = Date.now() + 300;  // 仅在真正拖动时抑制随后的 click
      if (Math.abs(dx) > 0) {
        // 双向滑动视觉反馈：右滑铜色(收藏)，左滑红色(取消)
        const clampedDx = Math.max(-120, Math.min(dx, 120));
        row.style.transform = `translateX(${clampedDx}px)`;
        const alpha = Math.min(Math.abs(dx) / SWIPE_THRESHOLD, 1);
        if (dx > 0) {
          // 右滑 → 铜色（收藏）
          row.style.boxShadow = `inset -30px 0 ${20 + Math.abs(dx)/3}px rgba(168,81,46,${alpha * 0.15})`;
          row.style.borderColor = `rgba(168,81,46,${alpha})`;
        } else {
          // 左滑 → 红色（取消收藏）
          row.style.boxShadow = `inset 30px 0 ${20 + Math.abs(dx)/3}px rgba(220,38,38,${alpha * 0.15})`;
          row.style.borderColor = `rgba(220,38,38,${alpha})`;
        }
      }
    }

    function onUp(e) {
      if (!dragging || !row) return;
      dragging = false;
      const dx = currentX - startX;
      row.style.transition = "transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease";
      let isFavoritesPage = row.closest("#fav-list") !== null;

      if (dx >= SWIPE_THRESHOLD) {
        // ===== 右滑 → 收藏 =====
        try {
          let item;
          if (cat === "fund") item = JSON.parse(row.dataset.fund);
          else item = JSON.parse(row.dataset.article);
          const added = addFavorite(item, cat);
          if (added) {
            row.classList.add("is-favorited");
            if (!row.querySelector(".fav-star")) {
              const star = document.createElement("span");
              star.className = "fav-star-inline";
              star.innerHTML = "★";
              star.setAttribute("aria-label", "已收藏");
              row.insertBefore(star, row.firstChild);
            }
            showToast("★ 已收藏");
          }
          row.style.transform = "translateX(0)";
          setTimeout(() => { row.style.transform = ""; row.style.boxShadow = ""; row.style.borderColor = ""; row._swiping = false; }, 300);
        } catch(err) { row._swiping = false; }
      } else if (dx <= -SWIPE_THRESHOLD) {
        // ===== 左滑 → 取消收藏 =====
        try {
          let item;
          if (cat === "fund") item = JSON.parse(row.dataset.fund);
          else item = JSON.parse(row.dataset.article);
          const removed = removeFavorite(item, cat);
          if (removed) {
            showToast("已取消收藏");
            if (isFavoritesPage) {
              // 收藏页：直接从 DOM 移除该行
              row.style.transform = "translateX(-120px)";
              row.style.opacity = "0";
              setTimeout(() => { row.remove(); checkFavoritesEmpty(cat); }, 280);
              row._swiping = false;
              return;  // 不恢复样式，行已被移除
            } else {
              // 列表页：移除星标
              row.classList.remove("is-favorited");
              const star = row.querySelector(".fav-star-inline");
              if (star) star.remove();
            }
          }
          row.style.transform = "translateX(0)";
          setTimeout(() => { row.style.transform = ""; row.style.boxShadow = ""; row.style.borderColor = ""; row._swiping = false; }, 300);
        } catch(err) { row._swiping = false; }
      } else {
        row.style.transform = "";
        row.style.boxShadow = "";
        row.style.borderColor = "";
        row._swiping = false;
      }
      // 延迟清除标记，确保 click 事件能读到它
      if (didSwipe && row) {
        const r = row;
        setTimeout(() => { if(r) r._swiping = false; }, 50);
      }
      row = null;
    }

    // 用事件委托绑定到容器
    const containers = document.querySelectorAll(containerSelector);
    containers.forEach(c => {
      c.addEventListener("mousedown", (e) => {
        if (!e.shiftKey || !e.target.closest(rowSelector)) return;
        // Shift 只用于列表范围多选，禁止浏览器把它解释为连续选字。
        window.getSelection().removeAllRanges();
        e.preventDefault();
      }, true);
      c.addEventListener("mousedown", onDown, { passive: true });
      c.addEventListener("mousemove", onMove, { passive: true });
      c.addEventListener("mouseup", onUp);
      c.addEventListener("mouseleave", () => { if (dragging) { dragging = false; if(row){row.style.transform="";row.style.boxShadow="";row.style.borderColor="";row._swiping=false;row=null;} } });
      c.addEventListener("touchstart", onDown, { passive: true });
      c.addEventListener("touchmove", onMove, { passive: true });
      c.addEventListener("touchend", onUp);
    });
  }

  // 检查收藏列表是否为空
  function checkFavoritesEmpty(cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    if ((fav[key] || []).length === 0) {
      const favList = $("#fav-list");
      const favEmptyHint = $("#fav-empty-hint");
      if (favList) favList.innerHTML = "";
      if (favEmptyHint) favEmptyHint.hidden = false;
      updateFavCounts();
    }
  }

  // 渲染已有收藏标记（页面加载/切换时）
  function renderExistingMarks(containerSelector, rowSelector, cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const favIds = new Set(fav[key].map(f => getFavId(f, cat)));
    document.querySelectorAll(`${containerSelector} ${rowSelector}`).forEach(row => {
      try {
        let item;
        if (cat === "fund") item = JSON.parse(row.dataset.fund);
        else item = JSON.parse(row.dataset.article);
        if (favIds.has(getFavId(item, cat))) {
          row.classList.add("is-favorited");
          if (!row.querySelector(".fav-star-inline")) {
            const star = document.createElement("span");
            star.className = "fav-star-inline";
            star.innerHTML = "★";
            row.insertBefore(star, row.firstChild);
          }
        }
      } catch(e) {}
    });
  }

  // ===== 多选 + 批量删除 =====
  function rowSelId(row) {
    if (row.dataset.selId) return row.dataset.selId;
    try {
      if (row.dataset.fund) return String(JSON.parse(row.dataset.fund).id);
      if (row.dataset.article) return JSON.parse(row.dataset.article).id;
    } catch (e) {}
    return null;
  }
  function rowSelKind(row) {
    if (row.dataset.selKind) return row.dataset.selKind;   // "article" | "fund" | "fav"
    if (row.dataset.fund) return "fund";
    if (row.dataset.article) return "article";
    return null;
  }
  function rangeSelectInContainer(container, targetRow, kind) {
    const rows = Array.from(container.querySelectorAll(".article-row, .fund-row"));
    const ids = rows.map(r => rowSelId(r));
    const targetId = rowSelId(targetRow);
    const anchorId = kind === "fav" ? state.lastAnchorFav
      : (kind === "fund" ? state.lastAnchorFund : state.lastAnchorArticle);
    const iA = ids.indexOf(anchorId);
    const iT = ids.indexOf(targetId);
    if (iA < 0 || iT < 0) return;
    const [lo, hi] = iA < iT ? [iA, iT] : [iT, iA];
    for (let i = lo; i <= hi; i++) {
      const rid = ids[i];
      if (rid == null) continue;
      if (kind === "fav") state.selFav.add(rid);
      else if (kind === "fund") state.selFunds.add(rid);
      else state.selArticles.add(rid);
    }
  }
  function handleRowClick(row, e) {
    if (row._swiping || Date.now() < _suppressClickUntil) return;  // 拖动/滑动抑制 click
    if (rowHasTextSelection(row)) return;  // 拖拽选中的文字不再触发行选中
    const kind = rowSelKind(row);
    const id = rowSelId(row);
    if (!id || !kind) return;

    if (kind === "fav") {
      if (e.shiftKey && state.lastAnchorFav) {
        rangeSelectInContainer(row.parentElement, row, "fav");
      } else if (e.ctrlKey || e.metaKey || state.continuousSelection) {
        if (state.selFav.has(id)) state.selFav.delete(id); else state.selFav.add(id);
        state.lastAnchorFav = id;
      } else {
        state.selFav.clear();
        state.selFav.add(id);
        state.lastAnchorFav = id;
      }
      updateSelectionUI();
      return;
    }

    const set = kind === "fund" ? state.selFunds : state.selArticles;
    const anchorKey = kind === "fund" ? "lastAnchorFund" : "lastAnchorArticle";
    if (e.shiftKey && state[anchorKey]) {
      rangeSelectInContainer(row.parentElement, row, kind);
    } else if (e.ctrlKey || e.metaKey || state.continuousSelection) {
      if (set.has(id)) set.delete(id); else set.add(id);
      state[anchorKey] = id;
    } else {
      set.clear();
      set.add(id);
      state[anchorKey] = id;
    }
    updateSelectionUI();
  }
  function handleRowDblClick(row) {
    if (row._swiping) return;  // 仅真正拖动时抑制 dblclick（双击不检查抑制窗口，避免误杀）
    if (rowHasTextSelection(row)) return;
    try {
      if (row.dataset.fund) openFundDrawer(JSON.parse(row.dataset.fund));
      else if (row.dataset.article) openDrawer(JSON.parse(row.dataset.article));
    } catch (e) {}
  }
  function rowHasTextSelection(row) {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    return row.contains(selection.anchorNode) || row.contains(selection.focusNode);
  }
  function updateSelectionUI() {
    document.querySelectorAll(".article-row, .fund-row").forEach(row => {
      const id = rowSelId(row);
      if (id == null) return;
      const kind = rowSelKind(row);
      let sel;
      if (kind === "fav") sel = state.selFav.has(id);
      else if (kind === "fund") sel = state.selFunds.has(id);
      else sel = state.selArticles.has(id);
      row.classList.toggle("is-selected", sel);
    });
    syncSelectedItemMetadata();
    const total = state.selArticles.size + state.selFunds.size + state.selFav.size;
    const bar = document.getElementById("bulk-delete-bar");
    if (!bar) return;
    const continuousButton = document.getElementById("bulk-continuous-selection");
    const deleteButton = document.getElementById("bulk-delete-btn");
    bar.hidden = total === 0 && !state.continuousSelection;
    document.getElementById("bulk-delete-count").textContent = state.continuousSelection
      ? `已选中 ${total} 项 · 连续删除已开启`
      : `已选中 ${total} 项`;
    if (deleteButton) deleteButton.disabled = total === 0;
    if (continuousButton) {
      continuousButton.classList.toggle("is-active", state.continuousSelection);
      continuousButton.setAttribute("aria-pressed", String(state.continuousSelection));
      continuousButton.textContent = state.continuousSelection ? "连续删除：开" : "连续删除";
    }
  }
  function clearSelection() {
    state.selArticles.clear();
    state.selFunds.clear();
    state.selFav.clear();
    state.lastAnchorArticle = null;
    state.lastAnchorFund = null;
    state.lastAnchorFav = null;
    state.selectedItems.article.clear();
    state.selectedItems.fund.clear();
    state.selectedItems.fav.clear();
    updateSelectionUI();
  }
  function selectionSetFor(kind) {
    if (kind === "fav") return state.selFav;
    if (kind === "fund") return state.selFunds;
    return state.selArticles;
  }
  function selectionItemTitle(item, kind) {
    if (kind === "fund" || item.project_name) return item.project_name || "未命名基金项目";
    return item.title || "未命名文章";
  }
  function favoriteCategoryFor(item, kind, row) {
    if (kind === "fund" || item.project_name) return "基金";
    if (row && row.dataset.selCat) return row.dataset.selCat;
    return item.category === "期刊" ? "期刊" : "公众号";
  }
  function syncSelectedItemMetadata() {
    document.querySelectorAll(".article-row, .fund-row").forEach(row => {
      const kind = rowSelKind(row);
      const id = rowSelId(row);
      if (!kind || id == null || !selectionSetFor(kind).has(id)) return;
      try {
        const item = JSON.parse(row.dataset.fund || row.dataset.article);
        state.selectedItems[kind].set(id, {
          id,
          kind,
          item,
          category: favoriteCategoryFor(item, kind, row),
          favorited: row.classList.contains("is-favorited"),
        });
      } catch (e) {}
    });
    ["article", "fund", "fav"].forEach(kind => {
      const selected = selectionSetFor(kind);
      state.selectedItems[kind].forEach((_, id) => {
        if (!selected.has(id)) state.selectedItems[kind].delete(id);
      });
    });
  }
  function selectedFavoriteItems() {
    syncSelectedItemMetadata();
    const protectedItems = [];
    ["article", "fund", "fav"].forEach(kind => {
      state.selectedItems[kind].forEach(entry => {
        const isSavedInFavorites = kind === "fav" || entry.favorited || isFavoritedAnywhere(entry.item, entry.kind);
        if (isSavedInFavorites) protectedItems.push(entry);
      });
    });
    return protectedItems;
  }
  function deselectItem(entry) {
    selectionSetFor(entry.kind).delete(entry.id);
    state.selectedItems[entry.kind].delete(entry.id);
  }

  const protectedDeleteModal = document.getElementById("protected-delete-modal");
  const protectedDeleteItemsEl = document.getElementById("protected-delete-items");
  const protectedDeleteSummaryEl = document.getElementById("protected-delete-summary");
  let protectedDeleteItems = [];
  let protectedDeleteLastFocus = null;

  function renderProtectedDeleteItems() {
    protectedDeleteItemsEl.innerHTML = protectedDeleteItems.map((entry, index) => `
      <li class="protected-delete-item">
        <div class="protected-delete-item__content">
          <span class="protected-delete-item__category">${escapeHtml(entry.category)}</span>
          <strong>${escapeHtml(selectionItemTitle(entry.item, entry.kind))}</strong>
        </div>
        <div class="protected-delete-item__choices" role="group" aria-label="${escapeHtml(selectionItemTitle(entry.item, entry.kind))} 的删除决定">
          <button type="button" class="protected-delete-choice ${entry.approved ? "" : "is-active"}" data-protected-index="${index}" data-protected-choice="abandon">放弃删除</button>
          <button type="button" class="protected-delete-choice protected-delete-choice--danger ${entry.approved ? "is-active" : ""}" data-protected-index="${index}" data-protected-choice="proceed">坚持删除</button>
        </div>
      </li>`).join("");
    const protectedCount = protectedDeleteItems.length;
    const approvedCount = protectedDeleteItems.filter(entry => entry.approved).length;
    const ordinaryCount = Math.max(0, selectedItemTotal() - protectedCount);
    const finalDeleteCount = approvedCount + ordinaryCount;
    protectedDeleteSummaryEl.textContent = `最终确认后将删除：${approvedCount} 项收藏内容、${ordinaryCount} 项未收藏内容。`;
    const confirmButton = document.getElementById("protected-delete-confirm");
    confirmButton.disabled = finalDeleteCount === 0;
    confirmButton.textContent = finalDeleteCount > 0
      ? `最终确认删除 ${finalDeleteCount} 项`
      : "没有可删除项";
  }
  function openProtectedDeleteModal(items) {
    protectedDeleteItems = items.map(entry => ({ ...entry, approved: false }));
    protectedDeleteLastFocus = document.activeElement;
    renderProtectedDeleteItems();
    protectedDeleteModal.hidden = false;
    requestAnimationFrame(() => protectedDeleteModal.querySelector(".protected-delete-choice")?.focus());
    showToast(`已拦截 ${items.length} 项收藏内容，请逐项确认`, true);
  }
  function closeProtectedDeleteModal() {
    protectedDeleteModal.hidden = true;
    protectedDeleteItems = [];
    if (protectedDeleteLastFocus && typeof protectedDeleteLastFocus.focus === "function") {
      protectedDeleteLastFocus.focus();
    }
    protectedDeleteLastFocus = null;
  }
  function selectedItemTotal() {
    return state.selArticles.size + state.selFunds.size + state.selFav.size;
  }
  async function refreshCurrentView() {
    try {
      if (state.view === "account" && state.currentAccount) {
        await loadAccountArticles(state.currentAccount, state.currentPage);
      } else if (state.view === "aggregate") {
        await loadAggregate(state.currentCategory, state.aggPage);
      } else if (state.view === "fund") {
        await loadFunds(state.fundKw, state.fundQ);
      }
    } catch (e) {}
    try { await loadOverview(); } catch (e) {}
  }
  async function doBulkDelete(skipFavoriteProtection = false) {
    if (!skipFavoriteProtection) {
      const protectedItems = selectedFavoriteItems();
      if (protectedItems.length) {
        openProtectedDeleteModal(protectedItems);
        return;
      }
    }
    if (selectedItemTotal() === 0) {
      showToast("没有可删除的选中项", true);
      return;
    }
    if (state.view === "favorites") {
      const fav = loadFavorites();
      const cat = state.favCat;
      const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
      const removeIds = state.selFav;
      fav[key] = (fav[key] || []).filter(f => !removeIds.has(getFavId(f, cat)));
      saveFavorites(fav);
      updateFavCounts();
      const n = removeIds.size;
      state.selFav.clear();
      showToast(`已从私人珍藏移除 ${n} 项`);
      renderFavoritesList(cat);
      updateSelectionUI();
      return;
    }
    const articleIds = [...state.selArticles];
    const fundIds = [...state.selFunds];
    const articleRecords = articleIds.map(id => {
      const item = (state.selectedItems.article.get(id) || {}).item || {};
      return {
        id,
        title: item.title,
        title_zh: item.title_zh,
        summary: item.summary,
        category: item.category,
        account: item.account,
        archive_date: item.date,
        url: item.url || item.link,
      };
    });
    const fundRecords = fundIds.map(id => {
      const item = (state.selectedItems.fund.get(id) || {}).item || {};
      return {
        id,
        project_name: item.project_name,
        principal: item.principal,
        institution: item.institution,
        ratify_no: item.ratify_no,
        hit_keywords: item.hit_keywords,
      };
    });
    let okCount = 0;
    try {
      if (articleIds.length) {
        const r = await fetchJSON("/api/articles/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: articleIds, records: articleRecords }),
        });
        okCount += (r.deleted || 0);
      }
      if (fundIds.length) {
        const r = await fetchJSON("/api/funds/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: fundIds, records: fundRecords }),
        });
        okCount += (r.deleted || 0);
      }
      showToast(`已删除 ${okCount} 项`);
    } catch (e) {
      showToast("删除失败：" + e.message, true);
    }
    clearSelection();
    await refreshCurrentView();
    if (_currentSnapDate) loadSnapshot(_currentSnapDate);
  }

  // 私人珍藏视图
  const favTabs = $("#fav-tabs");
  const favList = $("#fav-list");
  const favEmptyHint = $("#fav-empty-hint");

  function showFavorites(cat) {
    state.view = "favorites";
    state.favCat = cat || "公众号";
    document.querySelectorAll(".page").forEach(p => p.classList.remove("is-visible"));
    document.querySelector('.page[data-view="favorites"]').classList.add("is-visible");
    pageEyebrow.textContent = "FAVORITES / COLLECTION";
    pageTitle.textContent = "私人珍藏";
    setActiveNav("favorites");

    // 标签高亮
    favTabs.querySelectorAll(".fav-tab").forEach(t => {
      t.classList.toggle("is-active", t.dataset.favCat === state.favCat);
    });

    renderFavoritesList(state.favCat);
  }

  function renderFavoritesList(cat) {
    const fav = loadFavorites();
    const key = cat === "公众号" ? "mp" : (cat === "期刊" ? "journal" : "fund");
    const items = fav[key] || [];

    if (!items.length) {
      favList.innerHTML = "";
      favEmptyHint.hidden = false;
      return;
    }
    favEmptyHint.hidden = true;

    if (cat === "基金") {
      favList.innerHTML = items.map(f => `
        <div class="article-row is-favorited" data-fund='${escapeHtml(JSON.stringify(f))}' data-sel-id='${escapeHtml(String(getFavId(f, "基金")))}' data-sel-kind="fav" data-sel-cat="基金">
          <span class="fav-star-inline">★</span>
          <div class="article-row__main">
            <h4>${escapeHtml(f.project_name || "")}</h4>
            <p class="fund-row__meta">
              <span>${escapeHtml(f.project_admin || "")} · ${escapeHtml(f.depend_unit || "")}</span>
              <span>${escapeHtml(f.ratify_year || "")}→结题 ${escapeHtml(f.conclusion_year || "")}</span>
            </p>
          </div>
          <div class="article-row__arrow"><svg><use href="#i-arrow"/></svg></div>
        </div>`).join("");
      favList.querySelectorAll(".fund-row, .article-row[data-fund]").forEach(row => {
        row.addEventListener("click", (e) => handleRowClick(row, e));
        row.addEventListener("dblclick", () => handleRowDblClick(row));
      });
    } else {
      // 公众号 / 期刊：按日期分组
      const groups = {};
      items.forEach(a => { const d = a.date || "未知"; (groups[d] = groups[d] || []).push(a); });
      favList.innerHTML = Object.entries(groups).map(([date, list]) => `
        <div class="date-group">
          <div class="date-group__head"><span class="dot"></span><h3>${formatDateLabel(date)}</h3><span>${list.length} 篇</span></div>
          ${list.map(a => `
            <div class="article-row is-favorited" data-article='${escapeHtml(JSON.stringify(a))}' data-sel-id='${escapeHtml(String(getFavId(a, cat)))}' data-sel-kind="fav" data-sel-cat="${escapeHtml(cat)}">
              <span class="fav-star-inline">★</span>
              <div class="article-row__time">${formatTime(a.date_published)}</div>
              <div class="article-row__main">
                <h4>${escapeHtml(a.title)}</h4>
                <p class="article-row__subtitle">${escapeHtml(a.title_zh || a.summary || "")}</p>
              </div>
              <span class="cat-badge ${catClass(a.category)}">${escapeHtml(a.category || cat)}</span>
              <div class="article-row__arrow"><svg><use href="#i-arrow"/></svg></div>
            </div>`).join("")}
        </div>`).join("");
      favList.querySelectorAll(".article-row[data-article]").forEach(row => {
        row.addEventListener("click", (e) => handleRowClick(row, e));
        row.addEventListener("dblclick", () => handleRowDblClick(row));
      });
    }
    // 收藏页面也启用左滑删除
    setupSwipeMark("#fav-list", ".article-row", cat);
  }

  // 标签切换
  favTabs.addEventListener("click", (e) => {
    const tab = e.target.closest(".fav-tab");
    if (!tab) return;
    showFavorites(tab.dataset.favCat);
  });

  // 导航更新：在文件总控下面加"私人珍藏"
  const origRenderNav = renderNav;
  // 我们需要修改 renderNav 来添加私人珍藏入口。直接重写导航中的按钮生成部分：
  // （通过覆写 showView 的 meta 来支持 favorites 视图）

  // 更新 showView 支持 favorites
  const _origShowView = showView;
  showView = function(view) {
    state.view = view;
    state.currentAccount = null;
    clearSelection();   // 切换顶层视图时清空选择
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    const page = document.querySelector(`.page[data-view="${view}"]`);
    if (page) page.classList.add("is-visible");
    setActiveNav(view);
    const meta = {
      dashboard: ["PAPER MAP / 00", "论文观察台"],
      fund: ["FUND / NSFC", "国自然基金观察"],
      favorites: ["FAVORITES / COLLECTION", "私人珍藏"],
      trash: ["RECYCLE BIN / 7 DAYS", "回收站"],
    }[view] || ["", ""];
    pageEyebrow.textContent = meta[0];
    pageTitle.textContent = meta[1];
    if (view === "fund") { loadFunds(state.fundKw, state.fundQ); }
    if (view === "favorites") { showFavorites(state.favCat); }
    if (view === "trash") { loadTrash(state.trashCategory); }
  };

  // 初始化滑动标记（在文章渲染后调用）
  function initSwipeForCurrentView() {
    requestAnimationFrame(() => {
      const account = state.accounts.find(item => item.name === state.currentAccount);
      const accountCategory = (account && account.category) || state.currentCategory || "公众号";
      setupSwipeMark("#account-articles", ".article-row", accountCategory);
      setupSwipeMark("#fund-list", ".fund-row", "基金");
      renderExistingMarks("#account-articles", ".article-row", accountCategory);
      renderExistingMarks("#fund-list", ".fund-row", "基金");
    });
  }

  // 监听视图切换，初始化对应滑动
  const _origOpenAccount = openAccount;
  openAccount = function(name) {
    if (name !== state.currentAccount) clearSelection();
    _origOpenAccount(name);
    initSwipeForCurrentView();
  };

  // 拦截 renderArticlesInto 后初始化滑动
  const _origRenderArticlesInto = renderArticlesInto;
  renderArticlesInto = function(container, pageEl, articles) {
    _origRenderArticlesInto(container, pageEl, articles);
    // 判断当前容器类型确定 category
    const cat = container.id === "account-articles"
      ? ((state.accounts.find(account => account.name === state.currentAccount) || {}).category || state.currentCategory || "公众号")
      : (container.id === "aggregate-articles" ? state.currentCategory : "公众号");
    requestAnimationFrame(() => {
      setupSwipeMark("#" + container.id, ".article-row", cat);
      renderExistingMarks("#" + container.id, ".article-row", cat);
    });
  };

  // 拦截 renderFundList 后初始化滑动
  const _origRenderFundList = renderFundList;
  renderFundList = function(funds, data) {
    _origRenderFundList(funds, data);
    requestAnimationFrame(() => {
      setupSwipeMark("#fund-list", ".fund-row", "基金");
      renderExistingMarks("#fund-list", ".fund-row", "基金");
    });
  };

  // ===== 批量删除工具条 =====
  const bulkBar = document.getElementById("bulk-delete-bar");
  if (bulkBar) {
    document.getElementById("bulk-delete-btn").addEventListener("click", () => doBulkDelete());
    document.getElementById("bulk-continuous-selection").addEventListener("click", () => {
      state.continuousSelection = !state.continuousSelection;
      updateSelectionUI();
      showToast(state.continuousSelection
        ? "连续删除已开启：直接点击卡片即可累加选择"
        : "连续删除已关闭");
    });
    document.getElementById("bulk-clear-sel").addEventListener("click", () => clearSelection());
  }

  if (protectedDeleteModal) {
    protectedDeleteItemsEl.addEventListener("click", (e) => {
      const button = e.target.closest("[data-protected-index]");
      if (!button) return;
      const entry = protectedDeleteItems[Number(button.dataset.protectedIndex)];
      if (!entry) return;
      entry.approved = button.dataset.protectedChoice === "proceed";
      renderProtectedDeleteItems();
    });
    const cancelProtectedDelete = () => closeProtectedDeleteModal();
    document.getElementById("protected-delete-close").addEventListener("click", cancelProtectedDelete);
    document.getElementById("protected-delete-cancel").addEventListener("click", cancelProtectedDelete);
    protectedDeleteModal.querySelector("[data-protected-delete-close]").addEventListener("click", cancelProtectedDelete);
    document.getElementById("protected-delete-confirm").addEventListener("click", async () => {
      const abandoned = protectedDeleteItems.filter(entry => !entry.approved);
      abandoned.forEach(deselectItem);
      closeProtectedDeleteModal();
      updateSelectionUI();
      if (selectedItemTotal() === 0) {
        showToast("已放弃删除全部收藏内容");
        return;
      }
      // 未收藏项此刻才会进入删除流程，是否删除取决于上方最终确认。
      await doBulkDelete(true);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !protectedDeleteModal.hidden) cancelProtectedDelete();
    });
  }

  // ===== 回收站 =====
  const trashTabs = $("#trash-tabs");
  const trashList = $("#trash-list");
  const trashClearButton = $("#trash-clear-button");
  const trashSelectionBar = $("#trash-selection-bar");
  const trashSelectionCount = $("#trash-selection-count");
  let trashItems = [];
  let selectedTrashItems = new Set();
  let lastTrashAnchor = null;

  function trashSelectionKey(item) {
    return `${item.kind}:${item.id}`;
  }

  function clearTrashSelection() {
    selectedTrashItems.clear();
    lastTrashAnchor = null;
    updateTrashSelectionUI();
  }

  function updateTrashSelectionUI() {
    document.querySelectorAll(".trash-row[data-trash-key]").forEach(row => {
      row.classList.toggle("is-selected", selectedTrashItems.has(row.dataset.trashKey));
    });
    if (trashSelectionBar) trashSelectionBar.hidden = selectedTrashItems.size === 0;
    if (trashSelectionCount) trashSelectionCount.textContent = `已选中 ${selectedTrashItems.size} 项`;
  }

  function updateTrashCounts(data) {
    const values = {
      "nav-trash-count": data.total || 0,
      "trash-total-count": data.total || 0,
      "trash-mp-count": data.mp_count || 0,
      "trash-journal-count": data.journal_count || 0,
      "trash-fund-count": data.fund_count || 0,
    };
    Object.entries(values).forEach(([id, value]) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    });
  }

  async function loadTrashSummary() {
    const data = await fetchJSON("/api/trash");
    updateTrashCounts(data);
    return data;
  }

  function trashDateTime(value) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function renderTrash(data) {
    trashItems = data.items || [];
    updateTrashCounts(data);
    if (trashTabs) {
      trashTabs.querySelectorAll(".trash-tab").forEach(tab => {
        tab.classList.toggle("is-active", tab.dataset.trashCategory === state.trashCategory);
      });
    }
    const items = state.trashCategory
      ? trashItems.filter(item => item.category === state.trashCategory)
      : trashItems;
    const validKeys = new Set(trashItems.map(trashSelectionKey));
    selectedTrashItems.forEach(key => { if (!validKeys.has(key)) selectedTrashItems.delete(key); });
    if (!trashList) return;
    if (!items.length) {
      const tip = state.trashCategory ? `暂无${state.trashCategory}删除内容。` : "回收站目前为空。";
      trashList.innerHTML = `<div class="trash-empty">${tip}<br><small>删除内容在这里保留 7 天，期间可以恢复。</small></div>`;
      updateTrashSelectionUI();
      return;
    }
    trashList.innerHTML = items.map(item => {
      const source = item.kind === "fund"
        ? [item.payload && item.payload.principal, item.payload && item.payload.institution].filter(Boolean).join(" · ")
        : item.account;
      const period = `删除于 ${trashDateTime(item.deleted_at)} · 可恢复至 ${trashDateTime(item.expires_at)}`;
      return `
        <article class="trash-row ${selectedTrashItems.has(trashSelectionKey(item)) ? "is-selected" : ""}" data-trash-key="${escapeHtml(trashSelectionKey(item))}">
          <div class="trash-row__main">
            <div class="trash-row__meta">
              <span class="cat-badge ${catClass(item.category)}">${escapeHtml(item.category || "未分类")}</span>
              <span>${escapeHtml(period)}</span>
            </div>
            <div class="trash-row__title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
            ${source ? `<div class="trash-row__source">${escapeHtml(source)}</div>` : ""}
          </div>
          <button class="trash-row__restore" type="button" data-trash-restore-kind="${escapeHtml(item.kind)}" data-trash-restore-id="${escapeHtml(item.id)}">恢复</button>
        </article>`;
    }).join("");
    updateTrashSelectionUI();
  }

  async function loadTrash(category) {
    const nextCategory = category || "";
    if (nextCategory !== state.trashCategory) clearTrashSelection();
    state.trashCategory = nextCategory;
    if (trashList) trashList.innerHTML = `<p class="snapshot-loading">正在读取回收站…</p>`;
    try {
      const data = await loadTrashSummary();
      renderTrash(data);
    } catch (e) {
      if (trashList) trashList.innerHTML = `<div class="trash-empty">回收站加载失败：${escapeHtml(e.message)}</div>`;
      showToast("回收站加载失败：" + e.message, true);
    }
  }

  async function restoreTrashItem(kind, id) {
    try {
      const result = await fetchJSON("/api/trash/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: [{ kind, id }] }),
      });
      if (!result.restored) throw new Error("该内容已不在可恢复期限内");
      showToast(`已恢复 ${result.restored} 项`);
      clearTrashSelection();
      await loadTrash(state.trashCategory);
      await loadOverview();
    } catch (e) {
      showToast("恢复失败：" + e.message, true);
    }
  }

  if (trashTabs) {
    trashTabs.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-trash-category]");
      if (tab) loadTrash(tab.dataset.trashCategory);
    });
  }
  if (trashList) {
    trashList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-trash-restore-id]");
      if (button) {
        restoreTrashItem(button.dataset.trashRestoreKind, button.dataset.trashRestoreId);
        return;
      }
      const row = event.target.closest(".trash-row[data-trash-key]");
      if (!row || window.getSelection()?.toString()) return;
      const visibleItems = state.trashCategory
        ? trashItems.filter(item => item.category === state.trashCategory)
        : trashItems;
      const clickedIndex = visibleItems.findIndex(item => trashSelectionKey(item) === row.dataset.trashKey);
      if (clickedIndex < 0) return;
      const clickedKey = row.dataset.trashKey;
      if (event.shiftKey && lastTrashAnchor != null) {
        const anchorIndex = visibleItems.findIndex(item => trashSelectionKey(item) === lastTrashAnchor);
        if (anchorIndex >= 0) {
          if (!event.ctrlKey && !event.metaKey) selectedTrashItems.clear();
          const start = Math.min(anchorIndex, clickedIndex);
          const end = Math.max(anchorIndex, clickedIndex);
          for (let index = start; index <= end; index += 1) selectedTrashItems.add(trashSelectionKey(visibleItems[index]));
        } else {
          selectedTrashItems.add(clickedKey);
        }
      } else if (event.ctrlKey || event.metaKey) {
        if (selectedTrashItems.has(clickedKey)) selectedTrashItems.delete(clickedKey);
        else selectedTrashItems.add(clickedKey);
        lastTrashAnchor = clickedKey;
      } else {
        selectedTrashItems.clear();
        selectedTrashItems.add(clickedKey);
        lastTrashAnchor = clickedKey;
      }
      updateTrashSelectionUI();
    });
  }
  function selectedTrashPayload() {
    return trashItems
      .filter(item => selectedTrashItems.has(trashSelectionKey(item)))
      .map(item => ({ kind: item.kind, id: item.id }));
  }
  const trashRestoreSelected = $("#trash-restore-selected");
  const trashPurgeSelected = $("#trash-purge-selected");
  const trashClearSelection = $("#trash-clear-selection");
  if (trashRestoreSelected) {
    trashRestoreSelected.addEventListener("click", async () => {
      const items = selectedTrashPayload();
      if (!items.length) return;
      try {
        const result = await fetchJSON("/api/trash/restore", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
        });
        showToast(`已恢复 ${result.restored || 0} 项`);
        clearTrashSelection();
        await loadTrash(state.trashCategory);
        await loadOverview();
      } catch (e) { showToast("批量恢复失败：" + e.message, true); }
    });
  }
  if (trashPurgeSelected) {
    trashPurgeSelected.addEventListener("click", async () => {
      const items = selectedTrashPayload();
      if (!items.length) return;
      if (!window.confirm(`确定永久移出选中的 ${items.length} 项吗？之后将无法从回收站恢复。`)) return;
      try {
        const result = await fetchJSON("/api/trash/purge", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
        });
        showToast(`已永久移出 ${result.purged || 0} 项`);
        clearTrashSelection();
        await loadTrash(state.trashCategory);
        await loadOverview();
      } catch (e) { showToast("永久移出失败：" + e.message, true); }
    });
  }
  if (trashClearSelection) trashClearSelection.addEventListener("click", clearTrashSelection);
  if (trashClearButton) {
    trashClearButton.addEventListener("click", async () => {
      if (!window.confirm("确定清空回收站吗？清空后，这些内容将不再提供恢复入口。")) return;
      try {
        const result = await fetchJSON("/api/trash/clear", { method: "POST" });
        showToast(`已清空 ${result.cleared || 0} 条回收站记录`);
        await loadTrash(state.trashCategory);
        await loadOverview();
      } catch (e) {
        showToast("清空回收站失败：" + e.message, true);
      }
    });
  }

  // ===== 每日快照 =====
  const snapBody = $("#snapshot-body");
  const snapDateSelect = $("#snapshot-date-select");
  const snapRefreshBtn = $("#snapshot-refresh-btn");
  const deletionAuditBody = $("#deletion-audit-body");
  const deletionAuditDate = $("#deletion-audit-date");
  let _snapDates = [];       // 可用快照日期列表
  let _currentSnapDate = ""; // 当前显示的快照日期

  async function loadSnapshot(targetDate) {
    try {
      // 1) 加载日期列表（填充 select）
      const list = await fetchJSON("/api/snapshots");
      _snapDates = list.dates || [];
      _currentSnapDate = targetDate || (_snapDates[0] || "");

      // 填充日期选择器
      snapDateSelect.innerHTML = _snapDates.length
        ? _snapDates.map(d => `<option value="${d}" ${d === _currentSnapDate ? "selected" : ""}>${d}</option>`).join("")
        : '<option value="">暂无快照</option>';

      // 2) 加载具体快照数据
      if (!_currentSnapDate) {
        renderSnapshotEmpty();
        renderDeletionAuditEmpty();
        return;
      }
      const snap = await fetchJSON(`/api/snapshots/${_currentSnapDate}`);
      renderSnapshot(snap);
      await loadDeletionAudit(_currentSnapDate, snap);
    } catch (e) {
      snapBody.innerHTML = `<p class="snap-no-fetch">加载快照失败：${escapeHtml(e.message)}</p>`;
      renderDeletionAuditError(e);
    }
  }

  function renderSnapshot(s) {
    if (!s.fetched) {
      snapBody.innerHTML = `
        <div class="snap-no-fetch">
          <p><strong>${s.date || "今日"}</strong> 尚未执行拉取</p>
          <p style="margin-top:6px;font-size:.8rem;color:var(--ink-400)">点击右上角「现场抓取」开始今日论文采集</p>
        </div>`;
      return;
    }

    const mpTags = s.mp_sources && s.mp_sources.length
      ? s.mp_sources.map(n => `<span class="snap-tag snap-tag--mp"><svg width="12" height="12" viewBox="0 0 24 24"><use href="#i-paper"/></svg>${escapeHtml(n)}</span>`).join("")
      : `<span class="snap-tag snap-tag--none">无</span>`;
    const jnlTags = s.journal_sources && s.journal_sources.length
      ? s.journal_sources.map(n => `<span class="snap-tag snap-tag--journal"><svg width="12" height="12" viewBox="0 0 24 24"><use href="#i-search"/></svg>${escapeHtml(n)}</span>`).join("")
      : `<span class="snap-tag snap-tag--none">无</span>`;
    const fundTags = s.fund_keywords && s.fund_keywords.length
      ? s.fund_keywords.slice(0, 10).map(k => `<span class="snap-tag snap-tag--fund">${escapeHtml(k)}</span>`).join("")
          + (s.fund_keywords.length > 10 ? `<span class="snap-tag snap-tag--fund">+${s.fund_keywords.length - 10}</span>` : "")
      : `<span class="snap-tag snap-tag--none">0</span>`;

    const totalFetched = Number(s.total_fetched) || (
      (Number(s.mp_count) || 0) + (Number(s.journal_count) || 0) + (Number(s.fund_count) || 0)
    );
    snapBody.innerHTML = `
      <div class="snap-grid">
        <div class="snap-card">
          <div class="snap-card__label">拉取总数</div>
          <div class="snap-card__value snap-card__value--accent">${totalFetched}</div>
          <div class="snap-card__sub">公众号、期刊、基金项目合计</div>
        </div>
        <div class="snap-card">
          <div class="snap-card__label">公众号</div>
          <div class="snap-card__value">${s.mp_count || 0}</div>
          <div class="snap-card__sub">${s.mp_sources ? s.mp_sources.length : 0} 个来源</div>
        </div>
        <div class="snap-card">
          <div class="snap-card__label">期刊</div>
          <div class="snap-card__value">${s.journal_count || 0}</div>
          <div class="snap-card__sub">${s.journal_sources ? s.journal_sources.length : 0} 个来源</div>
        </div>
        <div class="snap-card">
          <div class="snap-card__label">基金项目</div>
          <div class="snap-card__value">${s.fund_count || 0}</div>
          <div class="snap-card__sub">${s.fund_keywords ? s.fund_keywords.length : 0} 个关键词</div>
        </div>
      </div>
      <div class="snap-sources">
        <div class="snap-sources-row" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px">
          <div>
            <div class="snap-sources__title">📱 公众号来源</div>
            <div class="snap-tags">${mpTags}</div>
          </div>
          <div>
            <div class="snap-sources__title">📰 期刊来源</div>
            <div class="snap-tags">${jnlTags}</div>
          </div>
          <div>
            <div class="snap-sources__title">💰 基金关键词</div>
            <div class="snap-tags">${fundTags}</div>
          </div>
        </div>
      </div>`;
  }

  function renderSnapshotEmpty() {
    snapBody.innerHTML = `<div class="snap-no-fetch"><p>暂无任何快照记录。</p><p style="margin-top:6px;font-size:.8rem;color:var(--ink-400)">执行一次「现场抓取」后将自动生成。</p></div>`;
  }

  async function loadDeletionAudit(date, snapshot) {
    deletionAuditBody.innerHTML = `<p class="snapshot-loading">读取删除记录…</p>`;
    try {
      const audit = await fetchJSON(`/api/deletion-audit?date=${encodeURIComponent(date)}`);
      renderDeletionAudit(audit, snapshot);
    } catch (e) {
      renderDeletionAuditError(e);
    }
  }
  function renderDeletionAudit(audit) {
    deletionAuditDate.textContent = `${formatDateLabel(audit.date)} · 最终确认的删除记录`;
    deletionAuditBody.innerHTML = `
      <div class="deletion-audit-grid">
        <div class="deletion-audit-card deletion-audit-card--danger"><span>删除总数</span><strong>${audit.total || 0}</strong><small>三类内容最终删除合计</small></div>
        <div class="deletion-audit-card"><span>公众号</span><strong>${audit.mp_count || 0}</strong><small>公众号文章</small></div>
        <div class="deletion-audit-card"><span>期刊</span><strong>${audit.journal_count || 0}</strong><small>期刊论文</small></div>
        <div class="deletion-audit-card"><span>基金项目</span><strong>${audit.fund_count || 0}</strong><small>基金项目</small></div>
      </div>`;
  }
  function renderDeletionAuditEmpty() {
    deletionAuditDate.textContent = "暂无可对账日期";
    deletionAuditBody.innerHTML = `<p class="deletion-audit-empty">生成每日拉取快照后，删除对账会显示在这里。</p>`;
  }
  function renderDeletionAuditError(error) {
    deletionAuditDate.textContent = "删除记录暂不可用";
    deletionAuditBody.innerHTML = `<p class="deletion-audit-empty">删除对账加载失败：${escapeHtml(error.message || String(error))}</p>`;
  }

  // 日期切换
  if (snapDateSelect) {
    snapDateSelect.addEventListener("change", () => {
      loadSnapshot(snapDateSelect.value);
    });
  }
  // 手动刷新按钮
  if (snapRefreshBtn) {
    snapRefreshBtn.addEventListener("click", () => { loadSnapshot(_currentSnapDate); });
  }

  // ===== 启动 =====
  checkHealth();
  loadOverview();
})();
