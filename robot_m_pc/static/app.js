const $ = (id) => document.getElementById(id);
const state = {
  sessionId: localStorage.getItem("consultationSession") || crypto.randomUUID(),
  stream: null,
  plan: null,
  busy: false,
  pollTimer: null,
  lastExecutionStatus: null,
  reportShownFor: null,
  reportPendingShownFor: null,
  captureSignature: "",
};
localStorage.setItem("consultationSession", state.sessionId);

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.remove("show"), 3500);
}

function addMessage(role, text, id = null) {
  const row = document.createElement("div");
  row.className = `message ${role}`;
  if (id) row.id = id;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "我" : "AI";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  row.append(avatar, bubble);
  $("messages").append(row);
  $("messages").scrollTop = $("messages").scrollHeight;
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    $("modelStatus").textContent = data.api_key_configured ? data.model : "未配置模型 Key";
    $("modelStatus").className = `status ${data.api_key_configured ? "ok" : "warn"}`;
    $("robotStatus").textContent = "机械臂真实自动模式";
    $("robotStatus").className = "status ok";
    const grid = $("drugGrid");
    grid.innerHTML = "";
    Object.entries(data.medicines).forEach(([slot, name]) => {
      const cell = document.createElement("div");
      cell.className = "drug";
      cell.dataset.slot = slot;
      cell.innerHTML = `<b>${name}</b><small>${String(slot).padStart(2, "0")} 号仓</small>`;
      grid.append(cell);
    });
  } catch { toast("无法读取应用状态"); }
}

async function toggleCamera() {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
    $("video").srcObject = null;
    $("videoEmpty").hidden = false;
    $("attachFrame").checked = false;
    $("attachFrame").disabled = true;
    $("analyzeFrame").disabled = true;
    $("cameraToggle").textContent = "开启摄像头拍摄";
    return;
  }
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: "user" }, audio: false });
    $("video").srcObject = state.stream;
    $("videoEmpty").hidden = true;
    $("attachFrame").disabled = false;
    $("attachFrame").checked = true;
    $("analyzeFrame").disabled = false;
    $("cameraToggle").textContent = "关闭摄像头";
  } catch (error) { toast(`摄像头无法开启：${error.message}`); }
}

function captureFrame() {
  if (!state.stream || !$("attachFrame").checked) return null;
  const video = $("video");
  const canvas = $("canvas");
  canvas.width = 640;
  canvas.height = Math.round(640 * (video.videoHeight || 480) / (video.videoWidth || 640));
  const ctx = canvas.getContext("2d");
  ctx.translate(canvas.width, 0);
  ctx.scale(-1, 1);
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", .72);
}

async function sendMessage() {
  const message = $("messageInput").value.trim();
  if (!message || state.busy) return;
  state.busy = true;
  $("sendButton").disabled = true;
  $("messageInput").value = "";
  addMessage("user", message + ($("attachFrame").checked ? "\n[已附当前摄像头画面]" : ""));
  addMessage("assistant thinking", "正在整理问诊信息…", "thinking");
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, message, image_data_url: captureFrame() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "请求失败");
    $("thinking")?.remove();
    addMessage("assistant", data.reply);
    if (data.pending_plan) renderPlan(data.pending_plan);
    if (data.execution) {
      applyExecution(data.execution);
      pollExecution(data.execution.plan_id);
    }
  } catch (error) {
    $("thinking")?.remove();
    addMessage("assistant", `暂时无法继续：${error.message}`);
  } finally {
    state.busy = false;
    $("sendButton").disabled = false;
    $("messageInput").focus();
  }
}

function renderPlan(plan) {
  state.plan = plan;
  state.lastExecutionStatus = null;
  state.reportShownFor = null;
  state.reportPendingShownFor = null;
  state.captureSignature = "";
  $("captureSection").hidden = true;
  $("captureGallery").innerHTML = "";
  $("planCard").classList.add("active");
  $("emptyPlan").hidden = true;
  $("planContent").hidden = false;
  $("planState").textContent = "机械臂执行中";
  $("planItems").innerHTML = "";
  document.querySelectorAll(".drug").forEach((cell) => cell.classList.remove("selected"));
  plan.items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "plan-item";
    row.innerHTML = `<span><b>${item.medicine_name}</b> × ${item.count}</span><span class="slot">${item.slot_index} 号仓</span>`;
    $("planItems").append(row);
    document.querySelector(`.drug[data-slot="${item.slot_index}"]`)?.classList.add("selected");
  });
  $("rationale").textContent = `演示决策：${plan.rationale}`;
  $("executionResults").textContent = "等待机械臂执行…";
}

function applyExecution(data) {
  const success = data.results.filter((item) => item.ok).length;
  const total = state.plan?.items.reduce((sum, item) => sum + item.count, 0) || data.results.length;
  $("planState").textContent = data.status === "completed"
    ? (data.report_status === "generating"
      ? "抓药完成 · 生成报告"
      : data.arm_state === "disabled" ? "抓药完成 · 已释放" : "抓药完成 · 释放失败")
    : data.status === "failed"
      ? (data.arm_state === "disabled" ? "执行失败 · 已释放" : "执行失败 · 释放失败")
      : success >= total ? "批量动作完成，正在整理结果" : `整批抓药中 · ${total} 个药仓`;
  const container = $("executionResults");
  container.innerHTML = "";
  renderCaptures(data.captures || []);
  if (!data.results.length) {
    container.textContent = `方案已显示，板卡正在连续处理 ${total} 个药仓…`;
  }
  data.results.forEach((item) => {
    const parsed = summarizeRobotDetail(item);
    const card = document.createElement("div");
    card.className = "execution-item";
    const head = document.createElement("div");
    head.className = "execution-head";
    const title = document.createElement("span");
    title.textContent = `第 ${item.sequence} 次 · ${item.slot_index} 号仓 ${item.medicine_name}`;
    const badge = document.createElement("span");
    badge.className = item.ok ? "execution-ok" : "execution-fail";
    badge.textContent = item.ok ? "成功" : "失败";
    head.append(title, badge);
    const summary = document.createElement("div");
    summary.className = "execution-summary";
    summary.textContent = parsed.summary;
    card.append(head, summary);
    if (parsed.raw) {
      const details = document.createElement("details");
      details.className = "execution-raw";
      const detailsTitle = document.createElement("summary");
      detailsTitle.textContent = "查看板卡动作日志";
      const pre = document.createElement("pre");
      pre.textContent = parsed.raw;
      details.append(detailsTitle, pre);
      card.append(details);
    }
    container.append(card);
  });
  if (data.robot_log?.length) {
    const details = document.createElement("details");
    details.className = "execution-raw batch-log";
    const title = document.createElement("summary");
    title.textContent = `查看整批板卡日志（${data.robot_log.length} 条）`;
    const pre = document.createElement("pre");
    pre.textContent = data.robot_log.join("\n");
    details.append(title, pre);
    container.append(details);
  }
  if (["disabled", "disable_failed"].includes(data.arm_state)) {
    const arm = document.createElement("div");
    arm.className = `arm-result ${data.arm_state === "disabled" ? "execution-ok" : "execution-fail"}`;
    arm.textContent = data.arm_state === "disabled"
      ? "✓ 机械臂使能已释放"
      : `✕ 机械臂释放失败：${data.arm_detail || "请查看日志"}`;
    container.append(arm);
  }
  if (data.report_status === "generating" && state.reportPendingShownFor !== data.plan_id) {
    addMessage("assistant report-pending", "抓药已完成，机械臂使能已释放。AI 正在生成详细总结报告…");
    state.reportPendingShownFor = data.plan_id;
  }
  if (data.report_status === "completed" && data.report && state.reportShownFor !== data.plan_id) {
    addMessage("assistant report", data.report);
    state.reportShownFor = data.plan_id;
  }
  if (data.status !== state.lastExecutionStatus) {
    if (data.status === "completed") toast(`真实抓药完成：${success} 次`);
    if (data.status === "failed") toast("抓药失败，详情已写入日志");
  }
  state.lastExecutionStatus = data.status;
}

function renderCaptures(captures) {
  const signature = JSON.stringify(captures.map((item) => [
    item.slot_index, item.image_url, item.detected, item.timed_out,
  ]));
  if (signature === state.captureSignature) return;
  state.captureSignature = signature;
  const section = $("captureSection");
  const gallery = $("captureGallery");
  gallery.innerHTML = "";
  section.hidden = captures.length === 0;
  captures.forEach((capture) => {
    const card = document.createElement("div");
    card.className = "capture-card";
    const visual = document.createElement("div");
    visual.className = "capture-image";
    if (capture.image_url) {
      const image = document.createElement("img");
      image.src = `${capture.image_url}?t=${Date.now()}`;
      image.alt = `${capture.slot_index} 号药仓抓取示意图`;
      image.loading = "lazy";
      image.addEventListener("error", () => { visual.textContent = "示意图加载失败"; });
      visual.append(image);
    } else {
      visual.textContent = capture.timed_out ? "视觉采集超时" : "暂无示意图";
    }
    const meta = document.createElement("div");
    meta.className = "capture-meta";
    const item = state.plan?.items.find((value) => value.slot_index === capture.slot_index);
    const name = document.createElement("b");
    name.textContent = `${capture.slot_index} 号仓${item ? ` · ${item.medicine_name}` : ""}`;
    const status = document.createElement("span");
    status.className = capture.detected ? "capture-detected" : "capture-missed";
    status.textContent = capture.timed_out ? "超时" : capture.detected ? "已框选" : "未检测";
    meta.append(name, status);
    card.append(visual, meta);
    gallery.append(card);
  });
}

function summarizeRobotDetail(item) {
  if (item.raw_detail) {
    return { summary: item.detail, raw: item.raw_detail };
  }
  try {
    const payload = JSON.parse(item.detail);
    const logs = payload?.data?.logs;
    const count = Array.isArray(logs) ? logs.length : 0;
    return {
      summary: item.ok ? `板卡执行完成${count ? `，包含 ${count} 条动作记录` : ""}` : (payload.message || "板卡执行失败"),
      raw: JSON.stringify(payload, null, 2),
    };
  } catch {
    const text = String(item.detail || "没有返回详细信息");
    return {
      summary: text.length > 120 ? `${text.slice(0, 120)}…` : text,
      raw: text.length > 120 ? text : "",
    };
  }
}

async function pollExecution(planId) {
  clearTimeout(state.pollTimer);
  if (state.plan?.plan_id !== planId) return;
  try {
    const response = await fetch(`/api/plans/${planId}/status`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "无法读取执行进度");
    if (state.plan?.plan_id !== planId) return;
    applyExecution(data);
    const terminal = ["completed", "failed", "expired"].includes(data.status);
    const armFinished = ["disabled", "disable_failed"].includes(data.arm_state);
    const reportFinished = ["completed", "failed"].includes(data.report_status);
    if (terminal && armFinished && reportFinished) return;
  } catch (error) {
    $("planState").textContent = "进度读取失败";
  }
  state.pollTimer = setTimeout(() => pollExecution(planId), 700);
}

async function analyzeCurrentFrame() {
  if (!state.stream) return toast("请先开启摄像头");
  $("attachFrame").checked = true;
  $("messageInput").value = "请结合我刚刚发送的摄像头画面进行望诊观察，并继续询问或给出演示决策。";
  await sendMessage();
}

function newSession() {
  if (!confirm("开始新的问诊？当前页面中的对话将清空。")) return;
  state.sessionId = crypto.randomUUID();
  state.plan = null;
  clearTimeout(state.pollTimer);
  state.lastExecutionStatus = null;
  state.reportShownFor = null;
  state.reportPendingShownFor = null;
  state.captureSignature = "";
  localStorage.setItem("consultationSession", state.sessionId);
  $("messages").innerHTML = "";
  addMessage("assistant", "你好，请告诉我现在最明显的症状和持续时间。为了完成望诊分析，也请点击右侧“开启摄像头”，然后发送当前画面。");
  $("planContent").hidden = true; $("emptyPlan").hidden = false; $("planState").textContent = "暂无";
  $("planCard").classList.remove("active");
  $("captureSection").hidden = true;
  $("captureGallery").innerHTML = "";
  document.querySelectorAll(".drug").forEach((cell) => cell.classList.remove("selected"));
}

$("sendButton").addEventListener("click", sendMessage);
$("cameraToggle").addEventListener("click", toggleCamera);
$("analyzeFrame").addEventListener("click", analyzeCurrentFrame);
$("newSession").addEventListener("click", newSession);
$("messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); }
});
window.addEventListener("beforeunload", () => state.stream?.getTracks().forEach((track) => track.stop()));
loadStatus();
