"use strict";
// 页面只保存 CSRF 证明；会话令牌由浏览器 HttpOnly Cookie 自动携带。
let user = null, csrf = "", threadId = "", activeRequest = null, selectedTicket = "";
const roles = {customer:"客户", technician:"维修人员", support:"客服", admin:"管理员"};
const labels = {product_model:"设备型号",issue_description:"故障描述",contact:"联系方式",device_info:"设备信息",impact:"影响范围",issue_type:"故障类型",priority:"优先级",assigned_to:"维修人员",ticket_id:"工单编号",new_status:"目标状态",previous_status:"原状态",note:"处理说明",description:"补充描述",assignee_id:"维修人员"};
const actions = {create_ticket:"创建工单",update_ticket_status:"更新状态",supplement_ticket:"补充信息",cancel_ticket:"取消工单",assign_ticket:"分派维修人员",set_ticket_priority:"调整优先级",handoff_ticket:"转人工"};

// 功能：取页面节点；内部调用 getElementById，避免重复选择表达式。
function byId(id) { return document.getElementById(id); }
// 功能：安全创建显示节点；textContent 让用户文字只作为文本，不执行 HTML。
function element(tag, text = "", cls = "") { const node = document.createElement(tag); node.textContent = text; node.className = cls; return node; }
// 功能：展示结果或错误；通过 textContent/hidden 更新提示，不输出请求凭据。
function notice(text, error = false) { const box = byId("notice"); box.textContent = text; box.className = error ? "error" : ""; box.hidden = !text; }
// 功能：统一访问同源 API；fetch 携带 Cookie 与 CSRF，json 解析结果，非成功状态抛出受控错误。
async function api(path, method = "GET", body, key) {
  const headers = {};
  if (method !== "GET") { headers["Content-Type"] = "application/json"; headers["X-CSRF-Token"] = csrf; }
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(path, {method, headers, credentials:"same-origin", body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.message || "请求未完成，请稍后重试"); error.status = response.status; throw error; }
  return data;
}
// 功能：防止连续点击并统一报错；回调执行后在 finally 中恢复按钮，失败时保留原提交编号。
async function busy(button, task) {
  button.disabled = true;
  try { await task(); } catch (error) { notice(error.message || "连接中断，请刷新后继续原请求。", true); }
  finally { button.disabled = button.closest("#chat-form") ? !!activeRequest : false; }
}
// 功能：浏览器重试沿用提交编号；SHA256 只保存正文指纹，sessionStorage 不保存密码、会话令牌或消息正文。
async function submitOnce(kind, path, body) {
  const slot = `submission:${user.user_id}:${threadId}:${kind}`;
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(body))))).map(v => v.toString(16).padStart(2,"0")).join("");
  let saved; try { saved = JSON.parse(sessionStorage.getItem(slot)); } catch { saved = null; }
  if (!saved || saved.digest !== digest) { saved = {digest, key:crypto.randomUUID()}; sessionStorage.setItem(slot, JSON.stringify(saved)); }
  try { const result = await api(path,"POST",body,saved.key); sessionStorage.removeItem(slot); return result; }
  catch (error) { if (error.status && error.status < 500 && error.status !== 409) sessionStorage.removeItem(slot); throw error; }
}
// 功能：进入已认证页面；api 读取会话列表，必要时创建会话，refresh 恢复业务状态。
async function enter(session) {
  user = session.user; csrf = session.csrf_token;
  byId("identity").textContent = `${user.user_id} · ${roles[user.role]}`;
  byId("login-panel").hidden = true; byId("workspace").hidden = false;
  byId("admin-panel").hidden = user.role !== "admin";
  let rows = (await api("/api/threads")).threads;
  if (!rows.length) { await api("/api/threads","POST"); rows = (await api("/api/threads")).threads; }
  const remembered = sessionStorage.getItem(`thread:${user.user_id}`);
  threadId = rows.some(row => row.thread_id === remembered) ? remembered : rows[0].thread_id;
  await refresh();
}
// 功能：刷新当前会话、确认卡片及工单；replaceChildren 清空旧显示，内容始终来自已授权 API。
async function refresh() {
  const rows = (await api("/api/threads")).threads;
  const select = byId("threads"); select.replaceChildren();
  for (const row of rows) { const option = element("option",row.title); option.value=row.thread_id; select.append(option); }
  select.value=threadId; sessionStorage.setItem(`thread:${user.user_id}`,threadId);
  const data = await api(`/api/threads/${encodeURIComponent(threadId)}`);
  activeRequest = data.active_request;
  const messages = byId("transcript"); messages.replaceChildren();
  if (!data.transcript.length) messages.append(element("p","从设备型号和故障表现开始描述。","muted"));
  for (const item of data.transcript) { const box = element("div","",`message ${item.role}`); box.append(element("strong",item.role === "user" ? "你" : "售后助手"),document.createTextNode(item.content)); messages.append(box); }
  messages.scrollTop=messages.scrollHeight;
  byId("recovery").hidden=!activeRequest;
  byId("recovery-text").textContent=activeRequest ? (activeRequest.answer || "这次请求尚未完成，可以继续处理或结束本次请求。") : "";
  byId("chat-form").querySelector("button").disabled=!!activeRequest;
  byId("thread-state").textContent=activeRequest ? "等待继续" : "已保存";
  renderConfirmations(data.pending_actions);
  await loadTickets();
}
// 功能：把冻结参数显示为人工可读的卡片；确认按钮只向服务器发送 operation_id 和用户选择。
function renderConfirmations(rows) {
  const box=byId("confirmations"); box.replaceChildren();
  if (!rows.length) box.append(element("p","暂时没有需要确认的操作。","muted"));
  for (const row of rows) {
    const card=element("div","","operation"); card.append(element("strong",actions[row.action] || "处理工单"));
    const dl=element("dl");
    for (const [key,value] of Object.entries(row.payload)) {
      if (!labels[key] || value === "") continue;
      const shown = key === "impact" ? ({single:"一台设备",multiple:"多台设备",all:"全部设备"}[value] || value) : key === "issue_type" ? ({network:"联网",bluetooth:"蓝牙",charging:"充电",safety:"安全故障",other:"其他"}[value] || value) : value;
      dl.append(element("dt",labels[key]),element("dd",String(shown)));
    }
    card.append(dl);
    let duplicate;
    if (row.payload.duplicates?.length) { const label=element("label","已有相似工单，仍然创建新工单"); duplicate=element("input"); duplicate.type="checkbox"; label.prepend(duplicate); card.append(label); }
    for (const cancel of [false,true]) {
      const button=element("button",cancel ? "取消本次操作" : "确认操作",cancel ? "secondary" : "");
      button.onclick=() => busy(button,async () => { const result=await api(`/api/operations/${row.operation_id}/confirm`,"POST",{thread_id:threadId,cancel,accept_duplicate:!!duplicate?.checked}); notice(cancel ? "本次操作已取消。" : `操作已完成${result.ticket ? `：${result.ticket.ticket_id} · ${result.ticket.status}` : ""}`); await refresh(); if(selectedTicket) await showTicket(selectedTicket); });
      card.append(button);
    }
    card.append(element("p",`请在 ${new Date(row.expires_at).toLocaleTimeString()} 前确认。`,"muted small")); box.append(card);
  }
}
// 功能：查询并绘制权限范围内工单；api 使用筛选参数，详情按钮调用 showTicket。
async function loadTickets() {
  const params=new URLSearchParams({thread_id:threadId,status:byId("status-filter").value});
  const data=await api(`/api/tickets?${params}`); const box=byId("tickets"); box.replaceChildren();
  if (!data.tickets.length) { box.append(element("p","当前没有符合条件的工单。","muted")); return; }
  const table=element("table"), head=element("tr");
  for(const label of ["工单编号","设备","状态","优先级","维修人员","操作"]) head.append(element("th",label));
  table.append(head);
  for(const row of data.tickets) { const tr=element("tr"); for(const key of ["ticket_id","product_model","status","priority","assigned_to"]) tr.append(element("td",row[key] || "待分派")); const td=element("td"), button=element("button","查看详情","secondary"); button.onclick=() => busy(button,() => showTicket(row.ticket_id)); td.append(button); tr.append(td); table.append(tr); }
  box.append(table); byId("ticket-limit").textContent=data.truncated ? "结果较多，请进一步筛选；当前展示前 200 条。" : `共 ${data.tickets.length} 张工单`;
}
// 功能：显示真实工单与处理历史；textContent 防止故障描述中的 HTML 被执行。
async function showTicket(id) {
  const data=await api(`/api/tickets/${encodeURIComponent(id)}?thread_id=${encodeURIComponent(threadId)}`); selectedTicket=id;
  const box=byId("ticket-detail"); box.replaceChildren(); const dl=element("dl","","detail");
  for(const key of ["ticket_id","product_model","issue_description","contact","priority","assigned_to"]) dl.append(element("dt",labels[key]),element("dd",data.ticket[key] || "未填写"));
  dl.append(element("dt","当前状态"),element("dd",data.ticket.status)); box.append(dl);
  const history=byId("history"); history.replaceChildren();
  for(const row of data.history) history.append(element("div",`${new Date(row.created_at).toLocaleString()} · ${row.operator_id} · ${actions[row.action] || row.action}\n${row.note || "操作已记录"}`,"history-item"));
  configureActions(data.ticket);
  byId("detail-panel").hidden=false;
}
// 功能：只呈现当前角色和状态适用的操作；filter 筛选状态、element 构造选项，服务器仍会再次检查权限。
function configureActions(ticket) {
  const form=byId("update-form"), owner=ticket.owner_id===user.user_id;
  const manager=["admin","support"].includes(user.role), worker=user.role==="admin" || (user.role==="technician" && ticket.assigned_to===user.user_id);
  form.hidden=ticket.status==="已关闭";
  const transitions={"待处理":["处理中","已关闭"],"处理中":["待用户确认"],"待用户确认":["已解决","处理中"],"已解决":["已关闭"],"已关闭":[]};
  const targets=transitions[ticket.status].filter(target=>target==="已关闭" ? owner || manager : ticket.status==="待用户确认" ? owner || worker : worker);
  form.elements.new_status.replaceChildren();
  for(const target of targets) form.elements.new_status.append(element("option",target));
  const choices=[];
  if(targets.length) choices.push("update_ticket_status");
  if(owner || manager || worker) choices.push("supplement_ticket");
  if(ticket.status==="待处理" && (owner || manager)) choices.push("cancel_ticket");
  choices.push("handoff_ticket");
  if(manager) choices.push("assign_ticket","set_ticket_priority");
  form.elements.action.replaceChildren();
  for(const action of choices) {const option=element("option",actions[action]); option.value=action; form.elements.action.append(option);}
  form.elements.action.dispatchEvent(new Event("change"));
}
// 功能：继续原请求；run 接口复用服务层检查点，finally 刷新数据库中的实际状态。
async function runRequest(id) {
  byId("thread-state").textContent="正在处理";
  try { const result=await api(`/api/requests/${id}/run`,"POST"); notice(result.success ? "本次处理已完成。" : result.answer,!result.success); }
  finally { await refresh(); }
}
// 功能：安装表单与按钮事件；FormData 取输入，submitOnce 负责提交幂等，业务写入仍需卡片确认。
function bindEvents() {
  byId("login-form").onsubmit=event => {event.preventDefault(); const form=event.currentTarget; busy(form.querySelector("button"),async()=>{ const session=await api("/api/login","POST",Object.fromEntries(new FormData(form))); form.reset(); notice(""); await enter(session); });};
  byId("logout").onclick=()=>busy(byId("logout"),async()=>{await api("/api/logout","POST"); sessionStorage.clear(); location.reload();});
  byId("new-thread").onclick=()=>busy(byId("new-thread"),async()=>{threadId=(await api("/api/threads","POST")).thread_id; selectedTicket=""; byId("detail-panel").hidden=true; await refresh();});
  byId("threads").onchange=()=>busy(byId("threads"),async()=>{threadId=byId("threads").value; selectedTicket=""; byId("detail-panel").hidden=true; await refresh();});
  byId("status-filter").onchange=()=>busy(byId("status-filter"),loadTickets);
  byId("retry").onclick=()=>busy(byId("retry"),()=>runRequest(activeRequest.request_id));
  byId("abandon").onclick=()=>busy(byId("abandon"),async()=>{await api(`/api/requests/${activeRequest.request_id}/abandon`,"POST"); await refresh();});
  byId("chat-form").onsubmit=event=>{event.preventDefault(); const form=event.currentTarget; busy(form.querySelector("button"),async()=>{const data=await submitOnce("chat",`/api/threads/${threadId}/requests`,{text:form.elements.text.value}); form.reset(); await refresh(); await runRequest(data.request_id);});};
  byId("create-form").onsubmit=event=>{event.preventDefault(); const form=event.currentTarget; busy(form.querySelector("button"),async()=>{await submitOnce("create",`/api/threads/${threadId}/proposals`,{action:"create_ticket",payload:Object.fromEntries(new FormData(form))}); form.reset(); notice("请核对右侧信息，并点击确认操作。"); await refresh();});};
  byId("update-form").elements.action.onchange=()=>{const action=byId("update-form").elements.action.value; document.querySelectorAll("[data-action]").forEach(node=>{node.hidden=node.dataset.action!==action;});};
  byId("update-form").onsubmit=event=>{event.preventDefault(); const form=event.currentTarget; busy(form.querySelector("button"),async()=>{const fields=Object.fromEntries(new FormData(form)); const payload={ticket_id:selectedTicket}; if(fields.action==="supplement_ticket") payload.description=fields.note; else payload.note=fields.note; for(const [action,key] of [["update_ticket_status","new_status"],["assign_ticket","assignee_id"],["set_ticket_priority","priority"]]) if(fields.action===action) payload[key]=fields[key]; await submitOnce("update",`/api/threads/${threadId}/proposals`,{action:fields.action,payload}); notice("操作已提交，请在待确认区域核对。"); await refresh();});};
  byId("staff-form").onsubmit=event=>{event.preventDefault(); const form=event.currentTarget; busy(form.querySelector("button"),async()=>{const data=Object.fromEntries(new FormData(form)); data.models=data.models.split(/[,，]/).map(v=>v.trim()).filter(Boolean); data.specialties=[data.specialty]; delete data.specialty; await api("/api/admin/users","POST",data); form.reset(); notice("账号已创建。");});};
}
// 功能：初始化页面；先绑定事件，再尝试通过 Cookie 恢复会话，未登录时保留登录表单。
async function start() { bindEvents(); try {await enter(await api("/api/session"));} catch(error) {if(error.status!==401) notice(error.message,true);} }
start();
