"use strict";

const $ = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("es-CO");
const labels = {academico:"Programa académico",tramites:"Trámites",bienestar:"Bienestar",bibliotecas:"Bibliotecas",calendario:"Calendario",sin_fuente:"Sin fuente suficiente",web:"Web",whatsapp:"WhatsApp"};
let sending = false;

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const selected = button.dataset.view;
    ["chat", "metrics"].forEach((view) => {
      $("view-" + view).hidden = view !== selected;
      $("nav-" + view).classList.toggle("active", view === selected);
      $("nav-" + view).setAttribute("aria-pressed", String(view === selected));
    });
  });
});

function message(text, who, sources = []) {
  const article = document.createElement("article");
  article.className = "message " + who;
  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = who === "user" ? "TÚ" : "NEXO";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  article.append(label, paragraph);
  if (sources.length) {
    const list = document.createElement("ul");
    list.className = "source-links";
    sources.forEach((source) => {
      let url;
      try { url = new URL(source.url); } catch { return; }
      if (url.protocol !== "https:" || !(url.hostname === "unal.edu.co" || url.hostname.endsWith(".unal.edu.co"))) return;
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = url.href;
      link.textContent = source.title + " ↗";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
      list.append(item);
    });
    article.append(list);
  }
  $("conversation").append(article);
  article.scrollIntoView({behavior:"smooth", block:"nearest"});
  return article;
}

async function send(text) {
  text = text.trim();
  if (sending || text.length < 2 || text.length > 2000) return;
  sending = true;
  $("send").disabled = true;
  document.querySelectorAll("[data-question]").forEach((button) => { button.disabled = true; });
  message(text, "user");
  $("question").value = "";
  const pending = message("Consultando las fuentes…", "assistant");
  try {
    const response = await fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message:text}), signal:AbortSignal.timeout(60000)});
    if (!response.ok) throw new Error(response.status === 429 ? "Has llegado al límite de consultas por minuto. Intenta de nuevo en un momento." : "No pude completar la consulta. Intenta de nuevo en un momento.");
    const data = await response.json();
    pending.remove();
    message(data.answer, "assistant", data.sources || []);
  } catch (error) {
    pending.remove();
    message(error.name === "TimeoutError" ? "La consulta tardó demasiado. Intenta de nuevo." : error.message === "Failed to fetch" ? "No hay conexión con el servicio. Intenta de nuevo." : error.message, "assistant error");
  } finally {
    sending = false;
    $("send").disabled = false;
    document.querySelectorAll("[data-question]").forEach((button) => { button.disabled = false; });
    $("question").focus({preventScroll:true});
  }
}

$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); send($("question").value); });
$("question").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) {event.preventDefault(); $("chat-form").requestSubmit();} });
document.querySelectorAll("[data-question]").forEach((button) => { button.addEventListener("click", () => send(button.dataset.question)); });

function distribution(target, values, total) {
  target.replaceChildren();
  const entries = Object.entries(values).sort((a,b) => b[1] - a[1]);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Aún no hay consultas registradas.";
    target.append(empty);
  }
  entries.forEach(([category, count]) => {
    const row = document.createElement("div");
    row.className = "category";
    const label = document.createElement("div");
    label.className = "category-label";
    const name = document.createElement("span");
    name.textContent = labels[category] || category.replaceAll("_", " ");
    const value = document.createElement("strong");
    value.textContent = number.format(count);
    label.append(name, value);
    const bar = document.createElement("meter");
    bar.min = 0;
    bar.max = Math.max(total, 1);
    bar.value = count;
    bar.setAttribute("aria-label", name.textContent + ": " + count);
    row.append(label, bar);
    target.append(row);
  });
}

$("metrics-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("metrics-status").textContent = "Consultando métricas…";
  $("metrics-content").hidden = true;
  try {
    const response = await fetch("/api/metrics", {headers:{"X-Admin-Token":$("admin-token").value}, signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error(response.status === 401 ? "Token de administración incorrecto." : response.status === 503 ? "Las métricas necesitan configuración del administrador." : "No fue posible consultar las métricas.");
    const data = await response.json();
    $("total").textContent = number.format(data.total_messages);
    $("grounded").textContent = (data.total_messages ? Math.round(data.grounded_messages / data.total_messages * 100) : 0) + "%";
    $("grounded-count").textContent = number.format(data.grounded_messages) + " consultas con referencias";
    $("latency").textContent = number.format(Math.round(data.avg_latency_ms)) + " ms";
    $("fallback").textContent = number.format(data.fallback_messages);
    distribution($("categories"), data.by_category, data.total_messages);
    distribution($("channels"), data.by_channel, data.total_messages);
    $("daily").replaceChildren();
    data.daily.slice().reverse().forEach((day) => {
      const row = document.createElement("tr");
      const date = document.createElement("td");
      date.textContent = day.date;
      const count = document.createElement("td");
      count.textContent = number.format(day.count);
      row.append(date, count);
      $("daily").append(row);
    });
    $("metrics-content").hidden = false;
    $("metrics-status").textContent = "Actualizado a las " + new Date().toLocaleTimeString("es-CO", {hour:"2-digit",minute:"2-digit"}) + ". Retención: " + data.retention_days + " días. Las consultas de prueba también se contabilizan.";
  } catch (error) {
    $("metrics-status").textContent = error.name === "TimeoutError" ? "La consulta tardó demasiado. Intenta de nuevo." : error.message;
  } finally {
    button.disabled = false;
  }
});
