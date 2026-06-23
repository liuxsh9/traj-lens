import { useState } from "react";
import type { Item } from "../api";

const TRUNCATE_AT = 500;

function typeLabel(it: Item): { text: string; cls: string } {
  if (it.type === "message") {
    const role = it.role ?? "message";
    const cls = role === "user" ? "l-user" : role === "assistant" ? "l-asst" : "l-user";
    return { text: role, cls };
  }
  if (it.type === "reasoning") return { text: "reasoning", cls: "l-reason" };
  if (it.type === "function_call") return { text: `call · ${it.name}`, cls: "l-call" };
  return { text: "tool_result", cls: "l-tool" };
}

function barCls(it: Item): string {
  if (it.type === "message") return it.role === "assistant" ? "b-asst" : "b-user";
  if (it.type === "reasoning") return "b-reason";
  if (it.type === "function_call") return "b-call";
  return "b-tool";
}

function TruncatedText({ text, className }: { text: string; className?: string }) {
  const [full, setFull] = useState(false);
  if (text.length <= TRUNCATE_AT) {
    return <div className={`item-text ${className ?? ""}`}>{text}</div>;
  }
  return (
    <div className={`item-text ${className ?? ""}`}>
      {full ? text : text.slice(0, TRUNCATE_AT) + "…"}
      <br />
      <button className="show-more" onClick={() => setFull(!full)}>
        {full ? "收起" : "显示更多"}
      </button>
    </div>
  );
}

function ItemBody({ item }: { item: Item }) {
  if (item.type === "message") {
    return <TruncatedText text={item.content ?? ""} className={item.role === "assistant" ? "" : ""} />;
  }
  if (item.type === "reasoning") {
    return <TruncatedText text={item.content ?? ""} className="muted" />;
  }
  if (item.type === "function_call") {
    const args = item.arguments ?? "";
    return <pre className="tool-block">{item.name}({args})</pre>;
  }
  if (item.type === "function_call_output") {
    const text = item.output ?? "";
    if (text.length <= TRUNCATE_AT) {
      return <pre className="tool-block out">{text}</pre>;
    }
    return <ExpandableToolOutput text={text} />;
  }
  return null;
}

function ExpandableToolOutput({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  return (
    <div>
      <pre className="tool-block out">{full ? text : text.slice(0, TRUNCATE_AT) + "…"}</pre>
      <button className="show-more" onClick={() => setFull(!full)}>
        {full ? "收起" : "显示更多"}
      </button>
    </div>
  );
}

export function ItemTranscript({ items }: { items: Item[] }) {
  return (
    <>
      {items.map((it, i) => {
        const { text, cls } = typeLabel(it);
        return (
          <div key={i} className="irow">
            <div className="ig">
              <span className={`ty ${cls}`}>{text}</span>
            </div>
            <div className="ib">
              <div className={`bar ${barCls(it)}`}>
                <ItemBody item={it} />
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
