(function () {
  "use strict";

  const state = {
    currentAccount: null,   // null 表示总览页
    currentPage: 1,
    pageSize: 10,
    totalPages: 1,
    accounts: [],
    fetchPolling: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const navStack = $("#nav-stack");
  const accountGrid = $("#account-grid");
  const metricStrip = $("#metric-strip");
  const topology = $("#topology");
  const accountArticles = $("#account-articles");
  const accountPagination = $("#account-pagination");
  const pageTitle = $("#page-title");
  const pageEyebrow = $("#page-eyebrow");
  const snapshotTime = $("#snapshot-time");
  const serviceDot = $("#service-dot");
  const serviceState = $("#service-state");
  const fetchButton = $("#fetch-button");
  const toast = $("#toast");

  // ===== 工具函数 =====
  async function fetchJSON(url, options) {
    const resp = await fetch(url, options);
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

  function formatTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso.replace("Z", "+00:00"));
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      return `${hh}:${mm}`;
    } catch (e) {
      return "";
    }
  }

  function formatDateLabel(dateStr) {
    // 2026.8.13 -> 2026年8月13日
    const p = dateStr.split(".");
    if (p.length === 3) {
      return `${p[0]}年${Number(p[1])}月${Number(p[2])}日`;
    }
    return dateStr;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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
      state.accounts = data.accounts;
      renderNav(data.accounts);
      renderMetrics(data);
      renderTopology(data.accounts);
      renderAccountGrid(data.accounts);
      snapshotTime.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      showToast("加载总览失败：" + e.message, true);
    }
  }

  function renderNav(accounts) {
    const items = accounts.map((a, i) => `
      <button class="nav-item" data-account="${escapeHtml(a.name)}" data-view="account">
        <svg><use href="#i-paper"/></svg><span>${escapeHtml(a.name)}</span><b>${a.article_count}</b>
      </button>`).join("");
    navStack.innerHTML = `
      <button class="nav-item is-active" data-account="" data-view="overview">
        <svg><use href="#i-grid"/></svg><span>全局总览</span><b>ALL</b>
      </button>${items}`;
    navStack.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const account = btn.dataset.account;
        if (account) openAccount(account); else showOverview();
      });
    });
  }

  function renderMetrics(data) {
    const lastDate = data.accounts.length
      ? (data.accounts.map((a) => a.last_date).filter(Boolean).sort().pop() || "—")
      : "—";
    metricStrip.innerHTML = `
      <div class="metric-cell"><span>关注公众号</span><strong>${data.total_accounts}</strong></div>
      <div class="metric-cell"><span>累计文章</span><strong>${data.total_articles}</strong></div>
      <div class="metric-cell"><span>归档天数</span><strong>${data.total_days}</strong></div>
      <div class="metric-cell is-alert"><span>最近归档</span><strong>${lastDate}</strong></div>`;
  }

  function renderTopology(accounts) {
    if (!accounts.length) {
      topology.innerHTML = '<div class="empty">暂无归档数据</div>';
      return;
    }
    const top = accounts.slice(0, 8);
    const core = `
      <div class="topology-core">
        <span>ACCOUNTS</span><strong>${accounts.length}</strong>
        <small>公众号归档源</small>
      </div>`;
    const nodes = top.map((a) => `
      <div class="topology-node">
        <div><strong>${escapeHtml(a.name)}</strong><span>${a.day_count} 天 · ${a.article_count} 篇</span></div>
        <b>${a.article_count}</b>
      </div>`).join("");
    topology.innerHTML = core + nodes;
  }

  function renderAccountGrid(accounts) {
    if (!accounts.length) {
      accountGrid.innerHTML = '<div class="empty">还没有归档数据，先点右上角「现场抓取」。</div>';
      return;
    }
    accountGrid.innerHTML = accounts.map((a) => {
      const isEmpty = a.article_count === 0;
      const tag = isEmpty ? '<b>暂无</b>' : `${a.day_count} DAYS <b>·</b> ${a.last_date || "—"}`;
      const emptyHint = isEmpty
        ? '<p class="account-card__hint">点击进入后可点右上角「现场抓取」尝试</p>'
        : "";
      return `
      <div class="account-card ${isEmpty ? "is-empty" : ""}" data-account="${escapeHtml(a.name)}">
        <p class="account-card__code">${tag}</p>
        <h4>${escapeHtml(a.name)}</h4>
        ${emptyHint}
        <div class="account-card__stats">
          <div><span>累计文章</span><strong>${a.article_count}</strong></div>
          <div class="is-alert"><span>归档天数</span><strong>${a.day_count}</strong></div>
        </div>
      </div>`;
    }).join("");
    accountGrid.querySelectorAll(".account-card").forEach((card) => {
      card.addEventListener("click", () => openAccount(card.dataset.account));
    });
  }

  // ===== 页面切换 =====
  function showOverview() {
    state.currentAccount = null;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    document.querySelector('[data-view="overview"]').classList.add("is-visible");
    pageTitle.textContent = "公众号论文全景";
    pageEyebrow.textContent = "PAPER MAP / 00";
    setActiveNav("");
  }

  function setActiveNav(account) {
    navStack.querySelectorAll(".nav-item").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.account === account);
    });
  }

  async function openAccount(account) {
    state.currentAccount = account;
    state.currentPage = 1;
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("is-visible"));
    document.querySelector('[data-view="account"]').classList.add("is-visible");
    pageTitle.textContent = account;
    pageEyebrow.textContent = "ACCOUNT / ARCHIVE";
    $("#account-page-title").textContent = account;
    const acc = state.accounts.find((a) => a.name === account);
    $("#account-desc").textContent = acc
      ? `累计 ${acc.article_count} 篇 · ${acc.day_count} 个归档日 · 最近 ${acc.last_date}`
      : "按日期倒序回溯每篇推文。";
    setActiveNav(account);
    await loadAccountArticles(account, 1);
  }

  // ===== 文章归档 =====
  async function loadAccountArticles(account, page) {
    try {
      const data = await fetchJSON(`/api/articles?account=${encodeURIComponent(account)}&page=${page}&size=${state.pageSize}`);
      console.log("[loadAccountArticles]", account, data);
      state.totalPages = data.total_pages || 1;
      renderTimeline(data.articles || []);
      renderPagination(data.page, data.total_pages || 1);
      $("#page-info").textContent = `${data.page} / ${data.total_pages || 1}`;
    } catch (e) {
      console.error("[loadAccountArticles] error:", e);
      showToast("加载文章失败：" + e.message, true);
      accountArticles.innerHTML = `<div class="empty empty--large">
        <p>加载失败</p><p class="empty-hint">${escapeHtml(e.message)}</p>
        <p class="empty-hint">请刷新页面重试，或检查后端是否在 8032 端口运行</p>
      </div>`;
    }
  }

  function renderTimeline(articles) {
    console.log("[renderTimeline] called, type=", typeof articles, "isArray=", Array.isArray(articles), "len=", articles && articles.length);
    if (!articles || !Array.isArray(articles) || !articles.length) {
      console.log("[renderTimeline] -> empty branch");
      accountArticles.innerHTML = `
        <div class="empty empty--large">
          <p>该公众号暂无归档文章</p>
          <p class="empty-hint">可能原因：① 公众号今天没发文 ② WeWe RSS 订阅源还没拉到该公众号</p>
          <p class="empty-hint">试试点右上角「现场抓取」，触发一次重新抓取</p>
        </div>`;
      return;
    }
    // 按日期分组
    const groups = {};
    articles.forEach((a) => {
      const d = a.date || "未知";
      if (!groups[d]) groups[d] = [];
      groups[d].push(a);
    });
    const html = Object.entries(groups).map(([date, list]) => `
      <div class="date-group">
        <div class="date-group__head"><span class="dot"></span><h3>${formatDateLabel(date)}</h3><span>${list.length} 篇</span></div>
        ${list.map((a) => `
          <div class="article-row" data-article='${escapeHtml(JSON.stringify(a))}'>
            <div class="article-row__time">${formatTime(a.date_published)}</div>
            <div class="article-row__main">
              <h4>${escapeHtml(a.title)}</h4>
              <p>${escapeHtml(a.summary || a.title)}</p>
            </div>
            <div class="article-row__arrow"><svg><use href="#i-arrow"/></svg></div>
          </div>`).join("")}
      </div>`).join("");
    console.log("[renderTimeline] html length=", html.length, "first 200:", html.slice(0, 200));
    accountArticles.innerHTML = html;
    // 强制 page 显示：JS 别处可能移除了 is-visible，这里重新加 + inline style 兜底
    const page = accountArticles.closest('.page');
    if (page) {
      document.querySelectorAll('.page').forEach(p => p.classList.remove('is-visible'));
      page.classList.add('is-visible');
      page.style.cssText = "display: block !important; min-height: 500px !important; visibility: visible !important; opacity: 1 !important;";
      console.log("[renderTimeline] fixed page is-visible:", page.classList.contains('is-visible'),
        "pageDisplay=", getComputedStyle(page).display, "pageH=", page.offsetHeight);
    } else {
      console.warn("[renderTimeline] #account-articles not inside .page!");
    }
    // 强制可见：覆盖任何外部 CSS（包括残留的 display:grid / display:none / height:0）
    accountArticles.style.cssText = "display: block !important; min-height: 300px !important; visibility: visible !important; opacity: 1 !important;";
    const dg = accountArticles.querySelector(".date-group");
    if (dg) dg.style.cssText = "display: block !important; min-height: 100px !important; visibility: visible !important;";
    const ar = accountArticles.querySelector(".article-row");
    if (ar) ar.style.cssText = "display: flex !important; min-height: 70px !important; visibility: visible !important; background: white !important; border: 1px solid #cbd1c8 !important;";
    const fc = accountArticles.firstElementChild;
    console.log("[renderTimeline] done, accountArticles.innerHTML length=", accountArticles.innerHTML.length,
      "| containerH=", accountArticles.offsetHeight, "px",
      "| childCount=", accountArticles.children.length,
      "| firstChildH=", fc ? fc.offsetHeight : 'N/A', "px",
      "| articleRowH=", ar ? ar.offsetHeight : 'N/A', "px",
      "| pageH=", page ? page.offsetHeight : 'N/A', "px");
    // 等一帧后再次确认 layout（强制同步）
    requestAnimationFrame(() => {
      const cs = getComputedStyle(accountArticles);
      const ar2 = accountArticles.querySelector(".article-row");
      const page2 = accountArticles.closest('.page');
      console.log("[renderTimeline raf]",
        "container display=" + cs.display,
        "minH=" + cs.minHeight,
        "containerH=" + accountArticles.offsetHeight,
        "firstChildH=" + (fc ? fc.offsetHeight : 'N/A'),
        "articleRowH=" + (ar2 ? ar2.offsetHeight : 'N/A'),
        "pageH=" + (page2 ? page2.offsetHeight : 'N/A'),
        "pageDisplay=" + (page2 ? getComputedStyle(page2).display : 'N/A'),
        "pageIsVisible=" + (page2 ? page2.classList.contains('is-visible') : 'N/A'));
    });
    accountArticles.querySelectorAll(".article-row").forEach((row) => {
      row.addEventListener("click", () => {
        try {
          openDrawer(JSON.parse(row.dataset.article));
        } catch (e) {
          openDrawer({ title: "文章", url: "#" });
        }
      });
    });
  }

  function renderPagination(page, totalPages) {
    $("#page-prev").disabled = page <= 1;
    $("#page-next").disabled = page >= totalPages;
    $("#page-info").textContent = `${page} / ${totalPages}`;
    $("#page-prev").onclick = () => { if (page > 1) { state.currentPage = page - 1; loadAccountArticles(state.currentAccount, state.currentPage); } };
    $("#page-next").onclick = () => { if (page < totalPages) { state.currentPage = page + 1; loadAccountArticles(state.currentAccount, state.currentPage); } };
  }

  // ===== 抽屉 =====
  const drawer = $("#detail-drawer");
  const drawerBackdrop = $("#drawer-backdrop");

  function openDrawer(article) {
    $("#drawer-title").textContent = article.account || "文章";
    $("#drawer-purpose").textContent = article.date ? formatDateLabel(article.date) : "";
    $("#drawer-stats").innerHTML = `
      <div class="drawer-stat"><span>公众号</span><strong>${escapeHtml(article.account || "—")}</strong></div>
      <div class="drawer-stat"><span>归档日期</span><strong>${article.date || "—"}</strong></div>
      <div class="drawer-stat"><span>发布时间</span><strong>${formatTime(article.date_published) || "—"}</strong></div>`;
    $("#article-full-title").textContent = article.title || "";
    $("#article-full-meta").innerHTML = `
      <span><svg><use href="#i-clock"/></svg>${escapeHtml(article.date_published || "")}</span>
      <span><svg><use href="#i-calendar"/></svg>${escapeHtml(article.date || "")}</span>`;
    $("#article-full-summary").textContent = article.summary || "（无摘要，请点击下方按钮查看原文）";
    const link = $("#article-full-link");
    link.href = article.url || "#";
    if (!article.url) link.style.display = "none"; else link.style.display = "";
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
            if (state.currentAccount) loadAccountArticles(state.currentAccount, 1);
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

  // ===== 启动 =====
  checkHealth();
  loadOverview();
})();
