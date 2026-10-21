// Shared attachment input for Web/PWA and both Desktop chat surfaces.
(() => {
  const form = document.getElementById("chat-form");
  if (!form) return;
  let selected = [];
  let busy = false;
  const panel = document.createElement("div");
  panel.className = "chat-attachments";
  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = "image/png,image/jpeg,image/webp";
  picker.multiple = true;
  picker.hidden = true;
  picker.setAttribute("aria-label", "画像を添付（4枚・各8MiBまで）");
  const status = document.createElement("span");
  const choose = document.createElement("button");
  choose.type = "button";
  choose.textContent = "画像を添付";
  choose.addEventListener("click", () => picker.click());
  status.setAttribute("role", "status");
  status.textContent = "画像: 4枚まで・各8MiB / 24時間で削除。クラウド送信は設定で許可が必要です。";
  const list = document.createElement("div");
  panel.append(choose, picker, status, list);
  form.before(panel);
  const session = () => localStorage.getItem("petit_session_id");
  const render = () => {
    list.replaceChildren();
    for (const item of selected) {
      const row = document.createElement("span");
      row.textContent = `${item.name} `;
      const preview = document.createElement("img");
      preview.src = item.preview;
      preview.alt = `${item.name}のプレビュー`;
      row.prepend(preview);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "削除";
      remove.disabled = busy;
      remove.setAttribute("aria-label", `${item.name}を削除`);
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try {
          const response = await fetch(`/api/attachments/${item.id}`, { method: "DELETE", headers: { "X-PETIT-Session": item.session } });
          if (!response.ok && response.status !== 404) throw new Error("削除できませんでした");
          selected = selected.filter((entry) => entry !== item);
          URL.revokeObjectURL(item.preview);
          if (!selected.length) status.textContent = "画像を削除しました。";
          render();
        } catch (error) { status.textContent = error.message; remove.disabled = false; }
      });
      row.append(remove);
      list.append(row);
    }
  };
  picker.addEventListener("change", async () => {
    const files = Array.from(picker.files || []);
    picker.value = "";
    if (busy) return;
    if (files.length + selected.length > 4 || files.some((file) => file.size > 8 * 1024 * 1024)) {
      status.textContent = "画像は4枚まで・各8MiB以下にしてください。";
      return;
    }
    busy = true;
    picker.disabled = true;
    choose.disabled = true;
    render();
    try {
      for (const file of files) {
        const owner = session();
        status.textContent = "画像を安全に確認しています…";
        const response = await fetch("/api/attachments", { method: "POST", headers: { "X-PETIT-Session": owner }, body: file,
          signal: AbortSignal.timeout(30000) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "画像を受け付けられませんでした");
        selected.push({ id: data.id, name: file.name, session: owner, preview: URL.createObjectURL(file) });
      }
      status.textContent = "画像を添付しました。送信すると解析します。";
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; picker.disabled = false; choose.disabled = false; render(); }
  });
  window.PetitChatAttachments = {
    ids: () => selected.map((item) => item.id),
    ready: () => !busy,
    lock(value) { busy = value; picker.disabled = value; choose.disabled = value; render(); },
    complete(ids) { selected = selected.filter((item) => {
      if (!ids.includes(item.id)) return true;
      URL.revokeObjectURL(item.preview);
      return false;
    }); status.textContent = "画像の解析が完了しました。新しい画像も添付できます。"; render(); },
  };
})();
