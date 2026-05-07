/**
 * 任务列表组件 — 用户认证 + 任务管理
 *
 * 提供：
 * - Token 管理（存/取/清）
 * - 用户登录状态检测
 * - 任务列表拉取与展示
 * - 任务状态轮询
 */

// ==================== Token 管理 ====================

const TOKEN_KEY = 'agent_token';
const USER_KEY = 'agent_user';

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

function saveAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function isLoggedIn() {
  return !!getToken();
}

// ==================== API 请求 ====================

async function apiRequest(url, options = {}) {
  const token = getToken();
  const headers = { ...options.headers };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401) {
    clearAuth();
    updateUserUI();
    return null;
  }
  return resp.json();
}

// ==================== 任务列表 ====================

async function fetchTasks(page = 1) {
  const data = await apiRequest(`/api/tasks?page=${page}&page_size=20`);
  return data || { tasks: [], page: 1 };
}

async function renderTaskList(page = 1) {
  const container = document.getElementById('taskListContent');
  if (!container) return;

  if (!isLoggedIn()) {
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px;">请先<a href="/login" style="color:var(--primary);">登录</a>后查看任务</div>';
    return;
  }

  const data = await fetchTasks(page);
  const tasks = data.tasks || [];

  if (tasks.length === 0) {
    container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:13px;">暂无分析任务</div>';
    return;
  }

  const STATUS_LABELS = {
    completed: '✅ 已完成',
    failed: '❌ 失败',
    running: '⏳ 进行中',
    pending: '📋 等待中',
  };

  let html = '';
  for (const t of tasks) {
    const statusLabel = STATUS_LABELS[t.status] || `📋 ${t.status}`;
    const progressText = t.progress ? (JSON.parse(t.progress).step || '') : '';
    const time = t.created_at ? new Date(t.created_at + 'Z').toLocaleString('zh-CN') : '';

    html += `<div style="padding:10px 12px;margin-bottom:6px;background:var(--bg);border-radius:8px;border:1px solid var(--border);font-size:13px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span><strong>${escapeHtml(t.product_name || '')}</strong></span>
        <span style="color:var(--text-muted);font-size:11px;">${statusLabel}</span>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px;">
        <span style="color:var(--text-muted);font-size:11px;">${time}</span>
      </div>`;

    if (progressText && t.status === 'running') {
      html += `<div style="color:var(--text-secondary);font-size:12px;margin-top:4px;">${escapeHtml(progressText)}</div>`;
    }
    if (t.status === 'failed' && t.error_message) {
      html += `<div style="color:var(--danger);font-size:12px;margin-top:4px;">${escapeHtml(t.error_message)}</div>`;
    }

    // 操作按钮
    const tokenParam = getToken() ? `?token=${encodeURIComponent(getToken())}` : '';
    html += '<div style="margin-top:6px;display:flex;gap:6px;align-items:center;">';
    if (t.status === 'completed') {
      html += `<a href="/api/tasks/${t.id}/download/md${tokenParam}" class="btn btn-outline" style="padding:3px 10px;font-size:12px;text-decoration:none;">📥 MD</a>
        <a href="/api/tasks/${t.id}/download/pdf${tokenParam}" class="btn btn-outline" style="padding:3px 10px;font-size:12px;text-decoration:none;">📥 PDF</a>`;
    }
    // 非运行中的任务可删除
    if (t.status !== 'running') {
      html += `<button onclick="deleteTask('${t.id}')" style="margin-left:auto;background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:12px;padding:2px 6px;" title="删除">🗑️</button>`;
    }
    html += '</div></div>';
  }
  container.innerHTML = html;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

async function deleteTask(taskId) {
  if (!confirm('确定要删除此任务吗？')) return;
  const data = await apiRequest(`/api/tasks/${taskId}`, { method: 'DELETE' });
  if (data) {
    renderTaskList();
  }
}

// ==================== 用户 UI ====================

function updateUserUI() {
  const userInfo = document.getElementById('userInfo');
  const userMenu = document.getElementById('userMenu');
  if (!userInfo || !userMenu) return;

  const user = getUser();
  if (user) {
    userInfo.innerHTML = `👤 ${escapeHtml(user.display_name || user.username)}`;
    userMenu.innerHTML = '<button onclick="doLogout()" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;font-size:13px;padding:4px 8px;">退出</button>';
  } else {
    userInfo.innerHTML = '<a href="/login" style="color:var(--primary);text-decoration:none;font-size:13px;">登录</a>';
    userMenu.innerHTML = '';
  }

  // 刷新任务列表
  if (document.getElementById('taskListContent')) {
    renderTaskList();
  }
}

function doLogout() {
  clearAuth();
  updateUserUI();
  // 断开旧 WebSocket 重连
  if (window.__appState) {
    window.__appState.token = null;
    window.__appState.user = null;
  }
  if (window.location.pathname === '/') {
    // 留在首页但清除认证状态
  }
}

// ==================== 自动轮询 ====================

let pollTimer = null;

function startTaskPolling(intervalMs = 5000) {
  stopTaskPolling();
  if (!isLoggedIn()) return;
  pollTimer = setInterval(() => {
    renderTaskList();
  }, intervalMs);
}

function stopTaskPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
  updateUserUI();

  // 如果首页有 taskListContent，启动轮询
  if (document.getElementById('taskListContent')) {
    renderTaskList();
    startTaskPolling(8000);
  }
});
