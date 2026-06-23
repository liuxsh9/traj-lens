export function TrimBar() {
  return (
    <div className="trimbar">
      <span className="faint" style={{ fontSize: 11 }}>✂ Trim 模式</span>
      <div className="rcheck">
        <span className="na">R1 边界</span>
        <span className="na">R2 工具配对</span>
        <span className="na">R3 上文</span>
        <span className="na">R4 结尾</span>
      </div>
      <span className="faint" style={{ marginLeft: "auto", fontSize: 11 }}>Slice 4 — 待实现</span>
    </div>
  );
}
