/**
 * 商品分析 Agent — 前端应用脚本
 *
 * 功能：
 * - SSE 流式通信（取代 WebSocket）
 * - 左侧对话区 + 右侧分析侧边栏
 * - 流式消息展示
 * - 分析进度跟踪与概览确认
 * - 报告下载
 * - 暗色模式切换
 */

// ==================== 状态管理 ====================

const STATE = {
  sessionId: null,
  isProcessing: false,
  pendingDecision: null,   // 'confirm' | 'reject' | 'terminate'：决策请求已发出、未确认
  currentStreamMsg: null,
  overviewData: null,
  analysisProgress: [],
  steps: [
    { id: 'params', label: '分析请求参数' },
    { id: 'collect', label: '采集商品数据' },
    { id: 'analyze', label: '多维度分析' },
    { id: 'review', label: '质量审核' },
    { id: 'overview', label: '生成分析概览' },
  ],
};

// ==================== 会话管理 ====================

function getSessionId() {
  if (!STATE.sessionId) {
    STATE.sessionId = 's_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
  }
  return STATE.sessionId;
}

function getToken() {
  return localStorage.getItem('agent_token');
}

// ==================== SSE 流式请求 ====================

async function sseFetch(url, body) {
  const token = getToken();
  let resp;
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch (e) {
    console.error('[SSE] 网络错误:', e);
    handleMessage({ type: 'error', content: '网络连接失败，请检查网络后重试' });
    return;
  }

  if (!resp.ok) {
    let detail = '请求失败';
    try {
      const err = await resp.json();
      detail = err.detail || detail;
    } catch (_) { /* ignore */ }
    handleMessage({ type: 'error', content: detail });
    return;
  }

  if (!resp.body) {
    handleMessage({ type: 'error', content: '浏览器不支持流式读取' });
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const msg = JSON.parse(line.slice(6));
            msg.type = currentEvent;
            handleMessage(msg);
          } catch (e) {
            console.error('[SSE] 解析错误:', e);
          }
        }
        // 空行表示事件结束
        if (line === '') {
          currentEvent = '';
        }
      }
    }
  } catch (e) {
    console.error('[SSE] 读取流错误:', e);
    handleMessage({ type: 'error', content: '网络中断，本次回复未完成，请重试' });
  }
  onStreamEnd();
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
      if (STATE.pendingDecision) {
        // 决策请求已被后端接受，收起概览卡并清空反馈框
        STATE.pendingDecision = null;
        setDecisionBusy(false);
        document.getElementById('overviewCard').style.display = 'none';
        document.getElementById('feedbackInput').value = '';
      }
      if (getToken()) {
        updateProgress(msg.content);
      }
      break;

    case 'overview':
      // 概览就绪
      removeTyping();
      STATE.overviewData = msg.data;
      STATE.pendingDecision = null;
      setDecisionBusy(false);
      if (getToken()) {
        showOverview(msg.data);
        setProcessing(false);
        input.disabled = true;
        sendBtn.disabled = true;
      } else {
        setProcessing(false);
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
      }
      break;

    case 'report_ready':
      // 报告就绪
      removeTyping();
      STATE.pendingDecision = null;
      setDecisionBusy(false);
      if (getToken()) {
        showReportPanel(msg);
      } else {
        setProcessing(false);
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
      }
      break;

    case 'error':
      removeTyping();
      // 收尾未完成的流式消息，避免残留 streaming 样式
      if (STATE.currentStreamMsg) {
        STATE.currentStreamMsg.classList.remove('streaming');
        STATE.currentStreamMsg = null;
      }
      if (STATE.pendingDecision) {
        // 决策请求失败：恢复概览卡，用户可重试或终止
        restoreDecisionCard();
        addMessage('❌ ' + msg.content, 'error');
        break;
      }
      addMessage('❌ ' + msg.content, 'error');
      setProcessing(false);
      input.disabled = false;
      sendBtn.disabled = false;
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

  const loggedIn = getToken();
  if (loggedIn) {
    resetProgress();
  } else {
    document.getElementById('analysisProgress').style.display = 'none';
    document.getElementById('analysisParams').style.display = 'none';
  }

  addMessage(content, 'user');
  input.value = '';
  autoResize(input);

  setProcessing(true);
  input.disabled = true;
  document.getElementById('sendBtn').disabled = true;

  STATE.currentStreamMsg = null;
  addTyping();
  if (loggedIn) showSidebarParams(content);

  sseFetch('/api/chat', { content, session_id: getSessionId() });
}

function quickInput(text) {
  document.getElementById('inputBox').value = text;
  autoResize(document.getElementById('inputBox'));
  sendMessage();
}

// ==================== 用户决策 ====================

function setDecisionBusy(busy) {
  ['confirmBtn', 'rejectBtn', 'terminateBtn'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = busy;
  });
  const feedback = document.getElementById('feedbackInput');
  if (feedback) feedback.disabled = busy;
}

function restoreDecisionCard() {
  // 决策失败后回到"等待决策"状态：概览卡恢复、输入区保持禁用
  STATE.pendingDecision = null;
  setDecisionBusy(false);
  STATE.isProcessing = false;
  removeTyping();
  if (STATE.overviewData) {
    showOverview(STATE.overviewData);
  }
}

function onStreamEnd() {
  // terminate 决策：后端不产生流事件，流结束即视为终止完成
  if (STATE.pendingDecision === 'terminate') {
    STATE.pendingDecision = null;
    setDecisionBusy(false);
    removeTyping();
    addMessage('分析已终止，可以输入新请求。', 'system');
    resetSidebar();
    setProcessing(false);
    document.getElementById('inputBox').focus();
  }
}

function confirmAnalysis() {
  if (STATE.isProcessing) return;
  STATE.pendingDecision = 'confirm';
  setDecisionBusy(true);
  STATE.isProcessing = true;
  addMessage('已确认，正在生成详细报告...', 'system');
  addTyping();
  sseFetch('/api/chat/decide', {
    session_id: getSessionId(),
    action: 'confirm',
  });
}

function rejectAnalysis() {
  if (STATE.isProcessing) return;
  const feedbackEl = document.getElementById('feedbackInput');
  const feedback = feedbackEl.value.trim();
  if (!feedback) {
    feedbackEl.focus();
    feedbackEl.style.borderColor = '#ef4444';
    setTimeout(() => feedbackEl.style.borderColor = '', 2000);
    return;
  }
  STATE.pendingDecision = 'reject';
  setDecisionBusy(true);
  STATE.isProcessing = true;
  addMessage('已提交反馈，正在重新分析...', 'system');
  resetProgress();
  addTyping();
  sseFetch('/api/chat/decide', {
    session_id: getSessionId(),
    action: 'reject',
    feedback,
  });
}

function terminateAnalysis() {
  if (STATE.isProcessing) return;
  if (!confirm('确定要终止当前分析吗？')) return;
  STATE.pendingDecision = 'terminate';
  setDecisionBusy(true);
  STATE.isProcessing = true;
  addMessage('正在终止当前分析...', 'system');
  sseFetch('/api/chat/decide', {
    session_id: getSessionId(),
    action: 'terminate',
  });
}

function startNewAnalysis() {
  document.getElementById('reportCard').style.display = 'none';
  document.getElementById('overviewCard').style.display = 'none';
  resetSidebar();
  if (getToken()) {
    document.getElementById('taskListCard').style.display = 'block';
  }
  setProcessing(false);
  document.getElementById('inputBox').disabled = false;
  document.getElementById('sendBtn').disabled = false;
  STATE.sessionId = Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
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
  card.style.display = 'flex';

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

  // 将操作按钮区域滚动到可视区
  setTimeout(() => {
    const actions = card.querySelector('.overview-actions');
    if (actions) {
      actions.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    // 同时确保整个侧边栏可以滚动
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
      sidebar.scrollTop = sidebar.scrollHeight;
    }
  }, 100);
}

// ==================== 侧边栏：报告下载 ====================

function showReportPanel(data) {
  document.getElementById('overviewCard').style.display = 'none';
  document.getElementById('analysisProgress').style.display = 'none';
  const card = document.getElementById('reportCard');
  card.style.display = 'block';

  document.getElementById('downloadMd').href = data.markdown_url;
  document.getElementById('downloadMd').download = data.markdown_filename;
  const pdfBtn = document.getElementById('downloadPdf');
  if (data.pdf_url) {
    pdfBtn.style.display = '';
    pdfBtn.href = data.pdf_url;
    pdfBtn.download = data.pdf_filename;
  } else {
    // PDF 生成失败时隐藏下载入口，避免给出死链接
    pdfBtn.style.display = 'none';
  }

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

  if (window.updateUserUI) {
    window.updateUserUI();
  }
  if (getToken()) {
    document.getElementById('taskListCard').style.display = 'block';
    if (window.renderTaskList) window.renderTaskList();
  }
});
