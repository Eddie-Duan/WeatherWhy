// 对话：一问一答，走 /api/explain 的 SSE。stage 事件用来把「正在做什么」显示出来，
// 最终 answer 才渲染成气泡（未校验通过的半成品不会先展示给用户）。

import { streamExplain, type Answer } from "./api";
import { answerBubble } from "./panels";

export interface ChatDeps {
  messages: HTMLElement;
  form: HTMLFormElement;
  input: HTMLInputElement;
  note: HTMLElement;
  place: () => string;
  days: () => number;
  onBusy: (busy: boolean) => void;
}

const esc = (value: string): string =>
  value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch] ?? ch);

function pushQuestion(container: HTMLElement, text: string): void {
  const bubble = document.createElement("div");
  bubble.className = "bubble question";
  bubble.textContent = text;
  container.append(bubble);
  container.scrollTop = container.scrollHeight;
}

function pushStage(container: HTMLElement, text: string): HTMLElement {
  const bubble = document.createElement("div");
  bubble.className = "bubble answer";
  bubble.innerHTML = `<span class="muted small">${esc(text)}</span>`;
  container.append(bubble);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

export function createChat(deps: ChatDeps): void {
  deps.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = deps.input.value.trim() || "这里的天气及成因是什么？";
    const place = deps.place();
    if (!place) {
      deps.note.textContent = "先查询一个地点。";
      return;
    }

    pushQuestion(deps.messages, question);
    deps.input.value = "";
    deps.onBusy(true);

    const stageBubble = pushStage(deps.messages, "正在组装事实包…");
    try {
      await streamExplain(place, deps.days(), (sse) => {
        if (sse.event === "stage") {
          const data = sse.data as { stage?: string; message?: string };
          stageBubble.textContent =
            data.stage === "explain" ? "事实包已就绪，正在调用解释层并校验引用…" : data.message ?? "处理中…";
        } else if (sse.event === "answer") {
          const data = sse.data as { answer: Answer };
          stageBubble.replaceWith(answerBubble(data.answer));
          deps.note.textContent = data.answer.degraded
            ? "本次未生成解释：已降级为事实罗列。"
            : "所有 ref 均已在 fact_pack 中校验通过。";
        } else if (sse.event === "error") {
          const data = sse.data as { error?: string };
          stageBubble.replaceWith(
            Object.assign(document.createElement("div"), {
              className: "bubble answer",
              textContent: `出错：${data.error ?? "未知错误"}`,
            }),
          );
        }
      });
    } catch (error) {
      stageBubble.replaceWith(
        Object.assign(document.createElement("div"), {
          className: "bubble answer",
          textContent: `请求失败：${error instanceof Error ? error.message : String(error)}`,
        }),
      );
    } finally {
      deps.onBusy(false);
      deps.messages.scrollTop = deps.messages.scrollHeight;
    }
  });
}
