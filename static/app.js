/**
 * 商品分析 Agent — 前端应用脚本
 *
 * 功能：
 * - WebSocket 实时通信
 * - 左侧对话区 + 右侧分析侧边栏
 * - 流式消息展示
 * - 分析进度跟踪与概览确认
 * - 报告下载
 * - 暗色模式切换
 */

// ==================== 状态管理 ====================

const STATE = {
  ws: null,
  sessionId: null,
  isProcessing: false,
  currentStreamMsg: null,
  overviewData: null,
  analysisProgress: [],
  // 分析进度步骤
  steps: [
    { id: 'params', label: '分析请求参数' },
    { id: 'collect', label: '采集商品数据' },
    { id: 'analyze', label: '多维度分析' },
    { id: 'review', label: '质量审核' },
    { id: 'overview', label: '生成分析概览' },
  ],
};

// ==================== WebSocket 管理 ====================

function getSessionId() {
  if (!STATE.sessionId) {
    STATE.sessionId = 's_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
  }
  return STATE.sessionId;
}

function getToken() {
  return localStorage.getItem('agent_token');
}

function connectWebSocket() {
  if (STATE.ws && STATE.ws.readyState === WebSocket.OPEN) return;

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = getToken();
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
  const url = `${protocol}//${location.host}/ws/${getSessionId()}${tokenParam}`;
  STATE.ws = new WebSocket(url);

  STATE.ws.onopen = () => console.log('[WS] 已连接');

  STATE.ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleMessage(msg);
  };

  STATE.ws.onclose = () => {
    console.log('[WS] 已断开，3秒后重连');
    setTimeout(connectWebSocket, 3000);
  };

  STATE.ws.onerror = () => console.error('[WS] 错误');
}

// ==================== 消息分发 ====================

function handleMessage(msg) {
  const input = document.getElementById('inputBox');
  const sendBtn = document.getElementById('sendBtn');

  switch (msg.type) {

    case 'token':
      // 流式 token
      if (!STATE.currentStreamMsg) {
        hideWelcome();
        STATE.currentStreamMsg = addMessage('', 'assistant streaming');
      }
      STATE.currentStreamMsg.textContent += msg.content;
      autoScroll();
      break;

    case 'done':
      // 流式结束
      if (STATE.currentStreamMsg) {
        STATE.currentStreamMsg.classList.remove('streaming');
        STATE.currentStreamMsg = null;
      }
      removeTyping();
      if (msg.intent === 'normal_chat') {
        setProcessing(false);
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
      }
      break;

    case 'status':
      // 状态提示
      removeTyping();
      // 更新进度
      updateProgress(msg.content);
      break;

    case 'overview':
      // 概览就绪
      removeTyping();
      STATE.overviewData = msg.data;
      showOverview(msg.data);
      setProcessing(false);
      input.disabled = true;
      sendBtn.disabled = true;
      break;

    case 'report_ready':
      // 报告就绪
      removeTyping();
      showReportPanel(msg);
      break;

    case 'error':
      removeTyping();
      addMessage('❌ ' + msg.content, 'error');
      setProcessing(false);
      input.disabled = false;
      sendBtn.disabled = false;
      break;

    case 'terminated':
      removeTyping();
      addMessage('分析已终止，可以输入新请求。', 'system');
      resetSidebar();
      setProcessing(false);
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
      break;

    case 'task_status':
      // 任务状态更新（仅当 task list 可见时刷新）
      if (document.getElementById('taskListCard').style.display !== 'none') {
        renderTaskList();
      }
      break;

    case 'task_list':
      // 任务列表数据（由 tasks.js 处理）
      break;
  }
}

// ==================== 发送消息 ====================

function sendMessage() {
  const input = document.getElementById('inputBox');
  const content = input.value.trim();
  if (!content || STATE.isProcessing) return;

  // 重置界面
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('reportCard').style.display = 'none';
  hideWelcome();
  resetProgress();

  addMessage(content, 'user');
  input.value = '';
  autoResize(input);

  setProcessing(true);
  input.disabled = true;
  document.getElementById('sendBtn').disabled = true;

  STATE.currentStreamMsg = null;
  addTyping();
  showSidebarParams(content);

  if (!STATE.ws || STATE.ws.readyState !== WebSocket.OPEN) {
    connectWebSocket();
    STATE.ws.onopen = () => {
      STATE.ws.send(JSON.stringify({ type: 'user_message', content }));
    };
  } else {
    STATE.ws.send(JSON.stringify({ type: 'user_message', content }));
  }
}

function quickInput(text) {
  document.getElementById('inputBox').value = text;
  autoResize(document.getElementById('inputBox'));
  sendMessage();
}

// ==================== 用户决策 ====================

function confirmAnalysis() {
  if (!STATE.ws || STATE.ws.readyState !== WebSocket.OPEN) return;
  STATE.ws.send(JSON.stringify({ type: 'decision', action: 'confirm' }));
  document.getElementById('overviewCard').style.display = 'none';
  addMessage('✅ 已确认，正在生成详细报告...', 'system');
  addTyping();
  STATE.isProcessing = true;
}

function rejectAnalysis() {
  if (!STATE.ws || STATE.ws.readyState !== WebSocket.OPEN) return;
  const feedback = document.getElementById('feedbackInput').value.trim();
  if (!feedback) {
    document.getElementById('feedbackInput').focus();
    document.getElementById('feedbackInput').style.borderColor = '#ef4444';
    setTimeout(() => document.getElementById('feedbackInput').style.borderColor = '', 2000);
    return;
  }
  STATE.ws.send(JSON.stringify({ type: 'decision', action: 'reject', feedback }));
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('feedbackInput').value = '';
  addMessage('🔄 已提交反馈，正在重新分析...', 'system');
  resetProgress();
  addTyping();
  STATE.isProcessing = true;
}

function terminateAnalysis() {
  if (!STATE.ws || STATE.ws.readyState !== WebSocket.OPEN) return;
  if (!confirm('确定要终止当前分析吗？')) return;
  STATE.ws.send(JSON.stringify({ type: 'decision', action: 'terminate' }));
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('feedbackInput').value = '';
}

function startNewAnalysis() {
  document.getElementById('reportCard').style.display = 'none';
  document.getElementById('overviewCard').style.display = 'none';
  resetSidebar();
  // 保持任务列表可见
  if (getToken()) {
    document.getElementById('taskListCard').style.display = 'block';
  }
  setProcessing(false);
  document.getElementById('inputBox').disabled = false;
  document.getElementById('sendBtn').disabled = false;
  STATE.sessionId = null;
  connectWebSocket();
  document.getElementById('inputBox').focus();
}

// ==================== 侧边栏：分析进度 ====================

function resetProgress() {
  STATE.analysisProgress = [];
  document.getElementById('analysisProgress').style.display = 'block';
  const list = document.getElementById('progressList');
  list.innerHTML = '';
  STATE.steps.forEach((step, i) => {
    const div = document.createElement('div');
    div.className = 'progress-step' + (i === 0 ? ' active' : '');
    div.id = 'step_' + step.id;
    div.innerHTML = `
      <span class="step-dot" id="dot_${step.id}"></span>
      <span class="step-label">${step.label}</span>
    `;
    list.appendChild(div);
  });
  updateProgress('分析请求参数');
}

function updateProgress(statusText) {
  // 根据状态文本匹配步骤
  if (statusText.includes('分析请求') || statusText.includes('参数')) markStepDone('params');
  if (statusText.includes('采集') || statusText.includes('数据')) {
    markStepDone('params');
    markStepDone('collect');
  }
  if (statusText.includes('维度分析') || statusText.includes('正在分析')) {
    markStepDone('params');
    markStepDone('collect');
    markStepDone('analyze');
  }
  if (statusText.includes('质量审核')) {
    markStepDone('params');
    markStepDone('collect');
    markStepDone('analyze');
    markStepDone('review');
  }
  if (statusText.includes('概览') || statusText.includes('审核通过')) {
    markStepDone('params');
    markStepDone('collect');
    markStepDone('analyze');
    markStepDone('review');
    markStepDone('overview');
  }
}

function markStepDone(id) {
  const step = document.getElementById('step_' + id);
  const dot = document.getElementById('dot_' + id);
  if (!step || step.classList.contains('done')) return;

  step.classList.remove('active');
  step.classList.add('done');
  dot.textContent = '✓';

  // 激活下一步
  const steps = STATE.steps;
  const idx = steps.findIndex(s => s.id === id);
  if (idx < steps.length - 1) {
    const next = document.getElementById('step_' + steps[idx + 1].id);
    if (next) next.classList.add('active');
  }
}

// ==================== 侧边栏：参数展示 ====================

function showSidebarParams(content) {
  document.getElementById('sidebarPlaceholder').style.display = 'none';
  document.getElementById('analysisParams').style.display = 'block';

  const list = document.getElementById('paramList');
  list.innerHTML = '';

  // 简单提取关键词
  const tags = [
    { label: '商品', value: content.length > 20 ? content.slice(0, 20) + '...' : content },
    { label: '时间', value: '近30天' },
  ];
  tags.forEach(t => {
    const span = document.createElement('span');
    span.className = 'param-tag';
    span.innerHTML = `${t.label}: ${t.value}`;
    list.appendChild(span);
  });
}

// ==================== 侧边栏：概览展示 ====================

function showOverview(data) {
  document.getElementById('analysisProgress').style.display = 'none';
  const card = document.getElementById('overviewCard');
  card.style.display = 'block';

  // 摘要
  document.getElementById('overviewSummary').textContent = data.summary || '';

  // 核心发现
  const findings = document.getElementById('overviewFindings');
  findings.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;font-weight:600;">核心发现</div>';
  (data.key_findings || []).forEach(f => {
    const div = document.createElement('div');
    div.className = 'finding-item';
    div.textContent = f;
    findings.appendChild(div);
  });

  // 维度摘要
  const dims = document.getElementById('overviewDims');
  dims.innerHTML = '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:6px;font-weight:600;">分析维度</div>';
  const dimData = data.dimension_summaries || {};
  Object.entries(dimData).forEach(([key, val]) => {
    const div = document.createElement('div');
    div.className = 'dim-tag';
    div.innerHTML = `<strong>${key}</strong>${val}`;
    dims.appendChild(div);
  });

  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ==================== 侧边栏：报告下载 ====================

function showReportPanel(data) {
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('analysisProgress').style.display = 'none';
  const card = document.getElementById('reportCard');
  card.style.display = 'block';

  document.getElementById('downloadMd').href = data.markdown_url;
  document.getElementById('downloadMd').download = data.markdown_filename;
  document.getElementById('downloadPdf').href = data.pdf_url;
  document.getElementById('downloadPdf').download = data.pdf_filename;

  addMessage('✅ 报告已生成，请在右侧下载。', 'system');
  autoScroll();

  setProcessing(false);
  document.getElementById('inputBox').disabled = false;
  document.getElementById('sendBtn').disabled = false;
  document.getElementById('inputBox').focus();
}

// ==================== 侧边栏：重置 ====================

function resetSidebar() {
  document.getElementById('sidebarPlaceholder').style.display = 'flex';
  document.getElementById('analysisParams').style.display = 'none';
  document.getElementById('analysisProgress').style.display = 'none';
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('reportCard').style.display = 'none';
  // 不隐藏 taskListCard（由登录状态控制）
}

// ==================== UI 辅助 ====================

function addMessage(content, className = 'assistant') {
  const container = document.getElementById('chatContainer');
  const msg = document.createElement('div');
  msg.className = `message ${className}`;
  msg.textContent = content;
  container.appendChild(msg);
  autoScroll();
  return msg;
}

function addTyping() {
  removeTyping();
  const container = document.getElementById('chatContainer');
  const typing = document.createElement('div');
  typing.className = 'typing-indicator';
  typing.id = 'typingIndicator';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'typing-dot';
    typing.appendChild(dot);
  }
  container.appendChild(typing);
  autoScroll();
}

function removeTyping() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

function autoScroll() {
  const section = document.querySelector('.chat-section');
  if (section) section.scrollTop = section.scrollHeight;
}

function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function setProcessing(val) {
  STATE.isProcessing = val;
  document.getElementById('sendBtn').disabled = val;
  document.getElementById('inputBox').disabled = val;
}

function hideWelcome() {
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'none';
}

// ==================== 暗色模式 ====================

function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  document.getElementById('themeToggle').textContent = isDark ? '🌙' : '☀️';
  localStorage.setItem('theme', isDark ? 'light' : 'dark');
}

// ==================== 侧边栏折叠 ====================

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const isHide = sidebar.classList.toggle('hide');
  document.getElementById('sidebarToggle').textContent = isHide ? '☰' : '✕';
}

// ==================== 键盘事件 ====================

document.addEventListener('DOMContentLoaded', () => {
  // 恢复主题
  const saved = localStorage.getItem('theme');
  if (saved) {
    document.documentElement.setAttribute('data-theme', saved);
    document.getElementById('themeToggle').textContent = saved === 'dark' ? '☀️' : '🌙';
  }

  const input = document.getElementById('inputBox');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // 初始化用户 UI（由 tasks.js 提供）
  if (window.updateUserUI) {
    window.updateUserUI();
  }
  // 已登录时显示任务列表
  if (getToken()) {
    document.getElementById('taskListCard').style.display = 'block';
    if (window.renderTaskList) window.renderTaskList();
  }

  connectWebSocket();
});
