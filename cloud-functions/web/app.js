"use strict";

const app = document.querySelector("#app");
const page = document.body.dataset.page;
const resourceId = document.body.dataset.resourceId;
const keyName = "realityAdminApiKey";
const statusLabels = {
  created: "作成済み",
  challenge_issued: "チャレンジ発行済み",
  waiting_device: "端末待機中",
  capturing: "証拠取得中",
  evidence_uploaded: "証拠受信済み",
  validating: "検証中",
  verified: "検証済み",
  proof_issued: "Proof 発行済み",
  failed: "失敗",
};
const errorMessages = {
  ERR_UNAUTHORIZED: "管理者 API キーが正しくありません。",
  ERR_AUTH_NOT_CONFIGURED: "管理者認証が設定されていません。",
  ERR_DEVICE_NOT_ALLOWED: "指定端末は登録されていません。",
  ERR_DEVICE_DISABLED: "指定端末は無効化されています。",
  ERR_DEVICE_COMMAND: "端末へチャレンジを配信できませんでした。",
  ERR_SESSION_EXPIRED: "指定時間内に操作が完了しませんでした。",
  ERR_BUTTON_COUNT: "ボタン操作がチャレンジ条件と一致しません。",
  ERR_FILE_MISSING: "画像または音声ファイルが不足しています。",
  ERR_HASH_MISMATCH: "証拠ファイルのハッシュが一致しません。",
  ERR_SIGNATURE_FAILED: "Proof の電子署名に失敗しました。",
  ERR_STORAGE_UNAVAILABLE: "保存先へ接続できませんでした。",
  ERR_INTERNAL: "内部エラーが発生しました。",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function panel(title) {
  const section = element("section", undefined, "panel");
  section.append(element("h2", title));
  app.append(section);
  return section;
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  const node = element("p", message, "error");
  app.prepend(node);
}

function adminKey() {
  return sessionStorage.getItem(keyName) || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Admin-Api-Key", adminKey());
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  const payload = await response.json();
  if (!response.ok) {
    const code = payload?.error?.code;
    throw new Error(
      errorMessages[code] || `処理に失敗しました (${code || `HTTP ${response.status}`})`
    );
  }
  return payload;
}

function addRows(section, rows) {
  const list = element("dl");
  for (const [name, value] of rows) {
    const row = element("div");
    row.append(element("dt", name), element("dd", value ?? "未設定"));
    list.append(row);
  }
  section.append(list);
}

function renderHome() {
  const hero = element("section", undefined, "hero");
  hero.append(
    element("h1", "現実の操作を、検証可能な記録へ。"),
    element("p", "登録済み Raspberry Pi で取得した物理操作、環境センサ、画像、音声、クラウド時刻を、Azure Key Vault の署名付き Proof Record として保存します。")
  );
  const actions = element("div", undefined, "actions");
  const start = element("a", "証明を開始する", "button");
  start.href = "/start";
  actions.append(start);
  hero.append(actions);
  app.append(hero);
  const notice = panel("利用上の注意");
  notice.append(element("p", "撮影・録音範囲にいる人の同意を確認してください。画像と音声は非公開 Blob に保存され、公開ページにはハッシュ値のみ表示されます。"));
}

async function loadDevices(select, button) {
  const payload = await api("/api/devices");
  select.replaceChildren();
  for (const device of payload.devices) {
    const option = element("option", `${device.display_name} (${device.status})`);
    option.value = device.device_id;
    option.disabled = device.status !== "active";
    select.append(option);
  }
  button.disabled = !select.value;
}

function renderStart() {
  const section = panel("証明を開始");
  const form = element("form");
  const keyLabel = element("label", "管理者 API キー");
  keyLabel.htmlFor = "admin-key";
  const keyInput = element("input");
  keyInput.id = "admin-key";
  keyInput.type = "password";
  keyInput.autocomplete = "off";
  keyInput.value = adminKey();
  const loadButton = element("button", "端末一覧を読み込む");
  loadButton.type = "button";
  const deviceLabel = element("label", "登録端末");
  deviceLabel.htmlFor = "device";
  const select = element("select");
  select.id = "device";
  const submit = element("button", "セッションを開始");
  submit.type = "submit";
  submit.disabled = true;
  form.append(
    keyLabel,
    keyInput,
    loadButton,
    deviceLabel,
    select,
    submit
  );
  section.append(form);

  async function refresh() {
    loadButton.disabled = true;
    try {
      sessionStorage.setItem(keyName, keyInput.value);
      await loadDevices(select, submit);
    } finally {
      loadButton.disabled = false;
    }
  }
  loadButton.addEventListener("click", () => refresh().catch(showError));
  keyInput.addEventListener("change", () => refresh().catch(showError));
  if (keyInput.value) refresh().catch(showError);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      sessionStorage.setItem(keyName, keyInput.value);
      const created = await api("/api/sessions/start", {
        method: "POST",
        body: JSON.stringify({device_id: select.value}),
      });
      location.assign(`/session/${encodeURIComponent(created.session_id)}`);
    } catch (error) {
      showError(error);
      submit.disabled = false;
    }
  });
}

async function renderSession() {
  const summary = panel("セッション状態");
  const statusNode = element("span", "読み込み中", "status");
  summary.append(statusNode);
  const detail = panel("チャレンジ");
  const timer = element("p");
  detail.append(timer);

  async function poll() {
    const session = await api(`/api/sessions/${encodeURIComponent(resourceId)}`);
    statusNode.textContent = statusLabels[session.status] || session.status;
    statusNode.className = `status status-${session.status}`;
    detail.querySelector("dl")?.remove();
    addRows(detail, [
      ["Session ID", session.session_id],
      ["Device ID", session.device_id],
      ["指示", session.challenge.instruction_ja],
      ["有効期限", session.expires_at],
      ["失敗理由", errorMessages[session.failure_code] || session.failure_code],
    ]);
    const remaining = Math.max(0, Date.parse(session.expires_at) - Date.now());
    timer.textContent = `残り時間: ${Math.ceil(remaining / 1000)} 秒`;
    if (session.status === "proof_issued" && session.proof_id) {
      location.assign(`/proof/${encodeURIComponent(session.proof_id)}`);
      return;
    }
    if (session.status !== "failed") setTimeout(() => poll().catch(showError), 1500);
  }
  await poll();
}

async function renderProof() {
  const payload = await api(`/api/admin/proofs/${encodeURIComponent(resourceId)}`);
  const proof = payload.proof;
  const manifest = payload.manifest || {};
  const summary = panel("Reality Proof Certificate");
  addRows(summary, [
    ["Proof ID", proof.proof_id],
    ["Device", proof.device_id],
    ["取得時刻", proof.captured_at],
    ["発行時刻", proof.created_at],
    ["結果", proof.challenge?.result === "verified" ? "検証済み" : proof.challenge?.result],
    ["Record Hash", proof.record_hash],
    ["署名方式", proof.signature_algorithm],
    ["Key ID", proof.key_id],
  ]);
  const evidence = panel("証拠データ");
  addRows(evidence, [
    ...Object.entries(manifest.sensors || {}),
    ["Image SHA-256", manifest.files?.image?.sha256],
    ["Audio SHA-256", manifest.files?.audio?.sha256],
  ]);
  const qrPanel = panel("QR 検証");
  const qr = element("img", undefined, "qr");
  qr.src = `/api/proofs/${encodeURIComponent(resourceId)}/qr`;
  qr.alt = "検証ページ QR コード";
  const link = element("a", "第三者向け検証ページを開く");
  link.href = `/verify/${encodeURIComponent(resourceId)}`;
  const paragraph = element("p");
  paragraph.append(link);
  qrPanel.append(qr, paragraph);
}

(async () => {
  try {
    if (page === "home") renderHome();
    else if (page === "start") renderStart();
    else if (page === "session") await renderSession();
    else if (page === "proof") await renderProof();
  } catch (error) {
    showError(error);
  }
})();
