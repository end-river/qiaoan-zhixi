import React, { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./style.css";
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error.message, info.componentStack);
  }
  render() {
    return this.state.failed ? (
      <div style={{ padding: 48, fontFamily: "sans-serif" }}>
        <h1>页面暂时无法显示</h1>
        <p>数据仍保存在本机，请刷新后重试。</p>
        <button onClick={() => window.location.reload()}>重新加载</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Boundary>
      <App />
    </Boundary>
  </React.StrictMode>,
);
