const PK_FIELD = "社員番号";
const FIELD_GROUPS = [
  {
    title: "基本情報",
    fields: [
      { key: "社員番号", label: "社員番号", readOnly: true },
      { key: "氏名", label: "氏名" },
      { key: "生年月日", label: "生年月日 (YYYYMMDD)" },
      { key: "郵便番号", label: "郵便番号" },
      { key: "都道府県", label: "都道府県" },
      { key: "市町村", label: "市町村" },
      { key: "番地", label: "番地" },
      { key: "建物", label: "建物" },
      { key: "電話番号", label: "電話番号" },
      { key: "メールアドレス", label: "メールアドレス" },
      { key: "LINE ID", label: "LINE ID" },
    ],
  },
  {
    title: "緊急連絡先（1）",
    fields: [
      { key: "緊急連絡先名1", label: "緊急連絡先名" },
      { key: "フリガナ1", label: "フリガナ" },
      { key: "続柄1", label: "続柄" },
      { key: "緊急電話番号1", label: "緊急電話番号" },
      { key: "緊急メールアドレス", label: "緊急メールアドレス" },
    ],
  },
  {
    title: "緊急連絡先（2）",
    fields: [
      { key: "緊急連絡先名2", label: "緊急連絡先名" },
      { key: "フリガナ2", label: "フリガナ" },
      { key: "続柄2", label: "続柄" },
      { key: "緊急電話番号2", label: "緊急電話番号" },
      { key: "緊急メールアドレス2", label: "緊急メールアドレス" },
    ],
  },
];
const FIELDS = FIELD_GROUPS.flatMap((group) => group.fields);

const state = {
  idToken: null,
};

const el = (id) => document.getElementById(id);

function showMessage(text) {
  el("message").textContent = text || "";
}

function cognitoIdpUrl() {
  return `https://cognito-idp.${window.APP_CONFIG.region}.amazonaws.com/`;
}

async function cognitoRequest(target, payload) {
  const res = await fetch(cognitoIdpUrl(), {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.message || data.__type || "認証に失敗しました");
  }
  return data;
}

async function login() {
  const username = el("login-username").value.trim();
  const password = el("login-password").value;
  if (!username || !password) {
    showMessage("社員番号とパスワードを入力してください");
    return;
  }

  showMessage("");
  try {
    const result = await cognitoRequest("InitiateAuth", {
      AuthFlow: "USER_PASSWORD_AUTH",
      ClientId: window.APP_CONFIG.userPoolClientId,
      AuthParameters: { USERNAME: username, PASSWORD: password },
    });

    onAuthenticated(result.AuthenticationResult.IdToken);
  } catch (err) {
    showMessage(err.message);
  }
}

function onAuthenticated(idToken) {
  state.idToken = idToken;
  sessionStorage.setItem("idToken", idToken);
  el("login-section").style.display = "none";
  el("profile-section").style.display = "block";
  loadProfile();
}

function renderForm(data) {
  const form = el("profile-form");
  form.innerHTML = "";
  FIELD_GROUPS.forEach((group) => {
    const section = document.createElement("section");
    section.className = "field-group";

    const heading = document.createElement("h2");
    heading.textContent = group.title;
    section.appendChild(heading);

    group.fields.forEach((field) => {
      const label = document.createElement("label");
      label.textContent = field.label;
      const input = document.createElement("input");
      input.id = `field-${field.key}`;
      input.value = data[field.key] || "";
      if (field.readOnly) input.readOnly = true;
      label.appendChild(input);
      section.appendChild(label);
    });

    form.appendChild(section);
  });
}

async function apiRequest(path, options = {}) {
  const res = await fetch(`${window.APP_CONFIG.apiBaseUrl}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${state.idToken}`,
    },
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.message || "通信に失敗しました");
  }
  return data;
}

async function loadProfile() {
  showMessage("");
  try {
    const data = await apiRequest("/me");
    renderForm(data);
  } catch (err) {
    showMessage(err.message);
  }
}

async function saveProfile() {
  showMessage("");
  const updates = {};
  FIELDS.forEach((field) => {
    if (field.readOnly) return;
    updates[field.key] = el(`field-${field.key}`).value;
  });

  try {
    await apiRequest("/me", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    showMessage("登録しました");
  } catch (err) {
    showMessage(err.message);
  }
}

function logout() {
  sessionStorage.removeItem("idToken");
  state.idToken = null;
  el("profile-section").style.display = "none";
  el("login-section").style.display = "block";
}

el("login-button").addEventListener("click", login);
el("save-button").addEventListener("click", saveProfile);
el("logout-button").addEventListener("click", logout);

// リロード時に既存セッションがあれば復元
const savedToken = sessionStorage.getItem("idToken");
if (savedToken) {
  onAuthenticated(savedToken);
}
