// 社区（Offer 茶水间）
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

// 职业问答模块
function getCommunityBoardMeta(board) {
  return COMMUNITY_FORUM_BOARD_META[board] || COMMUNITY_FORUM_BOARD_META.all;
}

function getCommunityForumPostById(postId) {
  return (communityForumState.posts || []).find((item) => String(item.id) === String(postId || "")) || null;
}

function upsertCommunityForumPost(updated) {
  const next = [];
  (communityForumState.posts || []).forEach((item) => {
    if (String(item.id) === String(updated.id)) {
      next.push({ ...item, ...updated });
    } else {
      next.push(item);
    }
  });
  communityForumState.posts = next;
}

function applyCommunityForumFeed(payload) {
  communityForumState.posts = Array.isArray(payload?.posts) ? payload.posts : [];
  communityForumState.boards = Array.isArray(payload?.boards) ? payload.boards : [];
  communityForumState.hotTags = Array.isArray(payload?.hot_tags) ? payload.hot_tags : [];
  communityForumState.stats = payload?.stats && typeof payload.stats === "object"
    ? payload.stats : { threads: 0, today_posts: 0, active_users: 0, unanswered: 0 };
  if (!getCommunityForumPostById(communityForumState.selectedPostId)) {
    communityForumState.selectedPostId = communityForumState.posts[0]?.id || "";
  }
}

function getCommunityForumHotScore(post) {
  const views = Number(post?.views || 0);
  const likes = Number(post?.likes || 0);
  const replies = Number(post?.reply_count || 0);
  const ageHours = (Date.now() / 1000 - Number(post?.created_at || 0)) / 3600;
  return (views * 0.5 + likes * 2 + replies * 3) / Math.max(1, Math.pow(ageHours + 2, 1.2));
}

function getCommunityForumFilteredPosts() {
  const query = String(communityForumState.query || "").trim().toLowerCase();
  const board = String(communityForumState.board || "all");
  const sort = String(communityForumState.sort || "hot");
  let posts = Array.isArray(communityForumState.posts) ? [...communityForumState.posts] : [];
  if (board !== "all") {
    posts = posts.filter((p) => String(p.board || "") === board);
  }
  if (query) {
    posts = posts.filter((p) => {
      const text = [p.title, p.content, ...(p.tags || [])].filter(Boolean).join(" ").toLowerCase();
      return text.includes(query);
    });
  }
  if (sort === "unanswered") posts = posts.filter(post => !Number(post.reply_count || 0));
  posts.sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    if (sort === "latest") return Number(b.created_at || 0) - Number(a.created_at || 0);
    if (sort === "unanswered") {
      const replyDiff = Number(a?.reply_count || 0) - Number(b?.reply_count || 0);
      if (replyDiff) return replyDiff;
      return Number(b.updated_at || 0) - Number(a.updated_at || 0);
    }
    return getCommunityForumHotScore(b) - getCommunityForumHotScore(a);
  });
  return posts;
}

// 切换三视图：list / detail / compose
function showForumView(view) {
  communityForumState.view = view;
  const viewMap = { list: "forumListView", detail: "forumDetailView", compose: "forumComposeView" };
  Object.values(viewMap).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.add("hidden");
  });
  const target = document.getElementById(viewMap[view]);
  if (target) target.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderCommunityForumBoardFilters() {
  const container = document.getElementById("forumBoardFilters");
  if (!container) return;
  const boards = communityForumState.boards.length ? communityForumState.boards
    : [{ key: "all", label: "全部讨论", count: 0 }, ...Object.keys(COMMUNITY_FORUM_BOARD_META).filter(key => key !== "all").map(key => ({ key, label: key, count: 0 }))];
  container.innerHTML = boards.map(item => {
    const key = String(item.key || item.label || "all");
    const active = key === communityForumState.board;
    return `<button type="button" data-forum-action="board" data-forum-value="${escHtml(key)}" class="forum-board-button${active ? ' is-active' : ''}" aria-pressed="${active}"><span class="forum-board-icon" aria-hidden="true">${escHtml(getCommunityBoardMeta(key).icon)}</span><strong>${key === 'all' ? '全部讨论' : escHtml(item.label || key)}</strong><small>${Number(item.count || 0)}</small></button>`;
  }).join("");
  const heading = document.getElementById("forumCurrentBoard");
  if (heading) heading.textContent = communityForumState.board === "all" ? "全部讨论" : communityForumState.board;
}

function renderCommunityForumSortFilters() {
  const container = document.getElementById("forumSortFilters");
  if (!container) return;
  container.innerHTML = [{ key: "hot", label: "热门讨论" }, { key: "latest", label: "最新发布" }, { key: "unanswered", label: "等待回复" }].map(item =>
    `<button type="button" data-forum-action="sort" data-forum-value="${item.key}" class="forum-sort-button${communityForumState.sort === item.key ? ' is-active' : ''}" aria-pressed="${communityForumState.sort === item.key}">${item.label}</button>`
  ).join("");
}

function renderCommunityForumHotTags() {
  const container = document.getElementById("forumHotTags");
  if (!container) return;
  container.innerHTML = communityForumState.hotTags.length ? communityForumState.hotTags.map(item =>
    `<button type="button" class="forum-tag" data-forum-action="tag" data-forum-value="${escHtml(item.tag || '')}">#${escHtml(item.tag || '')}<small>${Number(item.count || 0)}</small></button>`
  ).join("") : '<p class="forum-visibility-note">从你的第一条讨论开始。</p>';
}

function communityForumIcon(name) {
  const paths = {
    reply: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/>',
    view: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    like: '<path d="m20.8 4.6 0 0a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>'
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.reply}</svg>`;
}

function communityForumLikeButton(post) {
  return `<button type="button" class="forum-like-button${post.liked ? ' is-liked' : ''}" data-forum-action="like" data-forum-value="${escHtml(post.id)}" aria-label="${post.liked ? '取消点赞' : '点赞'}" aria-pressed="${Boolean(post.liked)}">${communityForumIcon('like')}<span>${Number(post.likes || 0)}</span></button>`;
}

function renderCommunityForumList() {
  const summary = document.getElementById("forumListSummary");
  const list = document.getElementById("forumThreadList");
  if (!summary || !list) return;
  if (communityForumState.loading && !communityForumState.loaded) {
    summary.textContent = "正在加载…";
    list.innerHTML = '<div class="forum-empty" role="status">正在整理讨论内容…</div>';
    return;
  }
  const posts = getCommunityForumFilteredPosts();
  summary.textContent = `${posts.length} 条讨论`;
  if (!posts.length) {
    list.innerHTML = '<div class="forum-empty"><p>还没有找到相关讨论</p><button type="button" class="forum-secondary-button" onclick="showForumView(\'compose\')">聊一个新话题</button></div>';
    return;
  }
  list.innerHTML = posts.map(post => {
    const author = post.author?.display_name || "匿名同学";
    const initial = Array.from(author)[0] || "同";
    const excerpt = String(post.content || "").slice(0, 150);
    return `<article class="forum-thread-card${post.pinned ? ' is-pinned' : ''}" data-board="${escHtml(post.board || '')}">
      <div class="forum-thread-head"><span class="forum-avatar" aria-hidden="true">${escHtml(initial)}</span><div class="forum-thread-author"><strong>${escHtml(author)}${post.author?.is_system ? ' · 官方' : ''}</strong><span>${escHtml(formatRelativeTimeCN(post.created_at))}</span></div><span class="forum-board-badge">${escHtml(post.board || '讨论')}</span>${post.pinned ? '<span class="forum-pin">置顶</span>' : ''}</div>
      <button type="button" class="forum-thread-title" data-forum-action="post" data-forum-value="${escHtml(post.id)}">${escHtml(post.title || '')}</button>
      <p class="forum-thread-excerpt">${escHtml(excerpt)}</p>
      <div class="forum-tags">${(post.tags || []).slice(0, 4).map(tag => `<button type="button" class="forum-tag" data-forum-action="tag" data-forum-value="${escHtml(tag)}">#${escHtml(tag)}</button>`).join('')}</div>
      <div class="forum-thread-footer"><div class="forum-thread-metrics"><span>${communityForumIcon('reply')}${Number(post.reply_count || 0)} 回复</span><span>${communityForumIcon('view')}${Number(post.views || 0)} 浏览</span>${!Number(post.reply_count || 0) ? '<span class="forum-unanswered">等一个好建议</span>' : ''}</div>${communityForumLikeButton(post)}</div>
    </article>`;
  }).join("");
}

function renderCommunityForumDetail() {
  const container = document.getElementById("forumThreadDetail");
  const badge = document.getElementById("forumDetailBadge");
  if (!container || !badge) return;
  const post = getCommunityForumPostById(communityForumState.selectedPostId);
  badge.className = "forum-board-badge";
  badge.dataset.board = post?.board || "";
  badge.textContent = post?.board || "讨论";
  if (!post) { container.innerHTML = ""; return; }
  const replies = Array.isArray(post.replies) ? post.replies : [];
  container.innerHTML = `<h3 class="forum-detail-title">${escHtml(post.title || '')}</h3><div class="forum-detail-meta">${escHtml(post.author?.display_name || '匿名同学')} · ${escHtml(formatRelativeTimeCN(post.created_at))} · ${Number(post.views || 0)} 浏览</div>
    <div class="forum-tags">${(post.tags || []).map(tag => `<button type="button" class="forum-tag" data-forum-action="tag" data-forum-value="${escHtml(tag)}">#${escHtml(tag)}</button>`).join('')}</div>
    <div class="forum-detail-content">${escHtml(post.content || '')}</div><div class="forum-thread-footer"><span class="forum-detail-meta">${replies.length} 条回复</span>${communityForumLikeButton(post)}${isSuperAdminUser() ? `<button type="button" class="forum-tag" style="color:#b91c1c" data-forum-action="delete" data-forum-value="${escHtml(post.id)}">删除帖子</button>` : ""}</div>
    <h4 class="forum-replies-title">一起聊聊</h4>
    ${replies.length ? replies.map(reply => `<article class="forum-reply"><span class="forum-avatar" aria-hidden="true">${escHtml(Array.from(reply.author?.display_name || '同')[0])}</span><div class="forum-reply-body"><div class="forum-thread-author"><strong>${escHtml(reply.author?.display_name || '匿名同学')}</strong><span>${escHtml(formatRelativeTimeCN(reply.created_at))}</span></div><p>${escHtml(reply.content || '')}</p></div></article>`).join('') : '<p class="forum-reply-empty">还没有回复，你的经验可能正好能帮上忙。</p>'}
    <form class="forum-reply-form" data-forum-reply-id="${escHtml(post.id)}"><label for="forumReplyInput">留下你的建议<textarea id="forumReplyInput" rows="4" maxlength="1200" minlength="4" required placeholder="分享一个思路，或者追问你想进一步了解的地方。"></textarea></label><button type="submit" class="forum-primary-button">发送回复</button></form>`;
}

function renderCommunityForum() {
  const threadCount = document.getElementById("forumThreadCount");
  const todayCount = document.getElementById("forumTodayCount");
  const activeUsers = document.getElementById("forumActiveUsers");
  const unansweredCount = document.getElementById("forumUnansweredCount");
  if (threadCount) threadCount.textContent = String(Number(communityForumState.stats?.threads || 0));
  if (todayCount) todayCount.textContent = String(Number(communityForumState.stats?.today_posts || 0));
  if (activeUsers) activeUsers.textContent = String(Number(communityForumState.stats?.active_users || 0));
  if (unansweredCount) unansweredCount.textContent = String(Number(communityForumState.stats?.unanswered || 0));
  renderCommunityForumBoardFilters();
  renderCommunityForumSortFilters();
  renderCommunityForumHotTags();
  renderCommunityForumList();
  if (communityForumState.view === "detail") {
    renderCommunityForumDetail();
  }
}

async function ensureCommunityForumLoaded(force = false) {
  if (communityForumState.loading) return;
  if (!force && communityForumState.loaded) {
    renderCommunityForum();
    return;
  }
  communityForumState.loading = true;
  const epoch = accountRequestEpoch;
  renderCommunityForum();
  try {
    const payload = await requestJson("/api/community-feed");
    applyCommunityForumFeed(payload);
    communityForumState.loaded = true;
    renderCommunityForum();
  } catch (error) {
    if (epoch !== accountRequestEpoch) return;
    showToast("论坛加载失败", error.message, "warning", 2200);
  } finally {
    if (epoch === accountRequestEpoch) {
      communityForumState.loading = false;
      renderCommunityForum();
    }
  }
}

function setCommunityForumBoard(board) {
  communityForumState.board = String(board || "all");
  showForumView("list");
  renderCommunityForum();
}

function setCommunityForumSort(sort) {
  communityForumState.sort = String(sort || "hot");
  renderCommunityForum();
}

function applyCommunityForumTag(tag) {
  const input = document.getElementById("forumSearchInput");
  const value = String(tag || "").trim();
  communityForumState.query = value;
  if (input) input.value = value;
  showForumView("list");
  renderCommunityForum();
}

async function selectCommunityPost(postId, options = {}) {
  const normalizedId = String(postId || "").trim();
  if (!normalizedId) return;
  communityForumState.selectedPostId = normalizedId;
  showForumView("detail");
  renderCommunityForumDetail();
  if (options.trackView === false || communityForumState.viewedIds[normalizedId]) return;
  communityForumState.viewedIds[normalizedId] = true;
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(normalizedId)}/view`, {
      method: "POST"
    });
    if (payload?.post) {
      upsertCommunityForumPost(payload.post);
      renderCommunityForumDetail();
    }
  } catch (error) {
    console.warn("community forum view update failed", error);
  }
}

async function submitCommunityPost() {
  const titleEl = document.getElementById("forumPostTitle");
  const boardEl = document.getElementById("forumPostBoard");
  const tagsEl = document.getElementById("forumPostTags");
  const contentEl = document.getElementById("forumPostContent");
  const title = String(titleEl?.value || "").trim();
  const board = String(boardEl?.value || "面经互助").trim();
  const tags = String(tagsEl?.value || "").trim();
  const content = String(contentEl?.value || "").trim();
  if (title.length < 4) {
    showToast("标题太短", "至少写 4 个字，让大家知道你想讨论什么。", "warning", 1800);
    return;
  }
  if (content.length < 10) {
    showToast("正文太短", "再补充一点背景和你的卡点，回复会更有针对性。", "warning", 1800);
    return;
  }
  try {
    const payload = await requestJson("/api/community-feed/posts", {
      method: "POST",
      body: { title, board, tags, content }
    });
    applyCommunityForumFeed(payload?.feed || payload);
    if (payload?.post?.id) {
      communityForumState.selectedPostId = payload.post.id;
      communityForumState.viewedIds[payload.post.id] = true;
    }
    if (titleEl) titleEl.value = "";
    if (tagsEl) tagsEl.value = "";
    if (contentEl) contentEl.value = "";
    showForumView("detail");
    renderCommunityForumDetail();
    addLiveActivity(`Community post published: ${title}`);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
    showToast("发帖成功", "新的讨论已经进入 Offer 茶水间。", "success", 1800);
  } catch (error) {
    showToast("发帖失败", error.message, "error", 2200);
  }
}

async function submitCommunityReply(postId) {
  const replyEl = document.getElementById("forumReplyInput");
  const content = String(replyEl?.value || "").trim();
  if (content.length < 4) {
    showToast("回复太短", "至少补充一句完整建议再发出去。", "warning", 1800);
    return;
  }
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(postId)}/reply`, {
      method: "POST",
      body: { content }
    });
    applyCommunityForumFeed(payload?.feed || payload);
    if (payload?.post?.id) {
      communityForumState.selectedPostId = payload.post.id;
      communityForumState.viewedIds[payload.post.id] = true;
    }
    if (replyEl) replyEl.value = "";
    renderCommunityForumDetail();
    addLiveActivity("Community reply sent");
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
    showToast("回复已发送", "你的建议已经出现在帖子详情里。", "success", 1800);
  } catch (error) {
    showToast("回复失败", error.message, "error", 2200);
  }
}

async function toggleCommunityPostLike(postId) {
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(postId)}/like`, {
      method: "POST"
    });
    if (payload?.post) {
      upsertCommunityForumPost(payload.post);
      // 同时刷新列表卡片（点赞数/状态）和详情视图
      renderCommunityForumList();
      if (communityForumState.view === "detail") {
        renderCommunityForumDetail();
      }
    }
  } catch (error) {
    showToast("点赞失败", error.message, "warning", 2000);
  }
}

async function deleteCommunityPost(postId) {
  if (!isSuperAdminUser()) return;
  if (!confirm("确认删除这篇帖子及其全部回复？删除后无法恢复。")) return;
  try {
    const payload = await requestJson(`/api/community-feed/posts/${encodeURIComponent(postId)}`, { method: "DELETE" });
    applyCommunityForumFeed(payload?.feed || payload);
    communityForumState.selectedPostId = "";
    showForumView("list");
    renderCommunityForum();
    showToast("已删除", "帖子已移除。", "success", 1600);
  } catch (error) {
    showToast("删除失败", error.message, "error", 2200);
  }
}

function scrollToForumComposer() {
  showForumView("compose");
  const target = document.getElementById("forumComposerCard");
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initCommunityForumEvents() {
  const root = document.getElementById("forum");
  if (root && !root.dataset.actionsBound) {
    root.dataset.actionsBound = "true";
    root.addEventListener("click", event => {
      const button = event.target.closest("[data-forum-action]");
      if (!button || !root.contains(button)) return;
      const { forumAction: action, forumValue: value } = button.dataset;
      if (action === "board") setCommunityForumBoard(value);
      else if (action === "sort") setCommunityForumSort(value);
      else if (action === "tag") applyCommunityForumTag(value);
      else if (action === "post") void selectCommunityPost(value);
      else if (action === "like") void toggleCommunityPostLike(value);
      else if (action === "delete") void deleteCommunityPost(value);
    });
    root.addEventListener("submit", event => {
      const form = event.target.closest("[data-forum-reply-id]");
      if (!form) return;
      event.preventDefault();
      void submitCommunityReply(form.dataset.forumReplyId);
    });
  }
  const searchInput = document.getElementById("forumSearchInput");
  if (searchInput && !searchInput.dataset.boundForumInput) {
    searchInput.addEventListener("input", (event) => {
      communityForumState.query = String(event.target?.value || "").trim();
      renderCommunityForum();
    });
    searchInput.dataset.boundForumInput = "1";
  }
  renderCommunityForum();
}

// ── 模型配置 ────────────────────────────────────────────────────────────────────
// 模型只在服务器 .env 里配置（AI_CHAT_BASE_URL / AI_CHAT_API_KEY / AI_CHAT_MODEL），页面里没有设置面板，
// 也不能选择模型。下面这些函数保留旧名字，是因为别的脚本仍会调用它们。
function toggleSettingsPanel(event) {
  if (event) event.stopPropagation();
}
