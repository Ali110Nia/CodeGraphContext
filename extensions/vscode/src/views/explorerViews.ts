import * as vscode from "vscode";
import { CgcService } from "../mcp/service";

class SimpleItem extends vscode.TreeItem {
  constructor(label: string, collapsibleState = vscode.TreeItemCollapsibleState.None) {
    super(label, collapsibleState);
  }
}

export class ReposTreeProvider implements vscode.TreeDataProvider<SimpleItem> {
  private readonly emitter = new vscode.EventEmitter<void>();
  public readonly onDidChangeTreeData = this.emitter.event;

  constructor(private readonly service: CgcService) {}

  refresh(): void {
    this.emitter.fire();
  }

  getTreeItem(element: SimpleItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<SimpleItem[]> {
    const repos = await this.service.listRepositories();
    if (!repos.length) {
      return [new SimpleItem("No indexed repositories")];
    }
    return repos.map((r) => {
      const item = new SimpleItem(r.repo_name ?? r.path ?? "Repository");
      item.description = r.path;
      return item;
    });
  }
}

export class BundlesTreeProvider implements vscode.TreeDataProvider<SimpleItem> {
  private readonly emitter = new vscode.EventEmitter<void>();
  public readonly onDidChangeTreeData = this.emitter.event;

  constructor(private readonly service: CgcService) {}

  refresh(): void {
    this.emitter.fire();
  }

  getTreeItem(element: SimpleItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<SimpleItem[]> {
    const bundles = await this.service.searchBundles("");
    if (!bundles.length) {
      return [new SimpleItem("No bundles found in registry")];
    }
    return bundles.slice(0, 30).map((bundle) => {
      const item = new SimpleItem(String(bundle.name ?? bundle.bundle_name ?? "Bundle"));
      item.description = String(bundle.version ?? "");
      return item;
    });
  }
}

export class WatchesTreeProvider implements vscode.TreeDataProvider<SimpleItem> {
  private readonly emitter = new vscode.EventEmitter<void>();
  public readonly onDidChangeTreeData = this.emitter.event;

  constructor(private readonly service: CgcService) {}

  refresh(): void {
    this.emitter.fire();
  }

  getTreeItem(element: SimpleItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<SimpleItem[]> {
    const paths = await this.service.listWatches();
    if (!paths.length) {
      return [new SimpleItem("No active watches")];
    }
    return paths.map((p) => new SimpleItem(p));
  }
}

export class CypherViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "cgc-cypher";
  private view?: vscode.WebviewView;
  private pendingQuery = "";

  constructor(private readonly service: CgcService) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = this.renderHtml();
    view.webview.onDidReceiveMessage(async (msg: { type: string; query?: string }) => {
      if (msg.type !== "run-query" || !msg.query) {
        return;
      }
      try {
        const rows = await this.service.runCypher(msg.query);
        view.webview.postMessage({ type: "query-result", rows });
      } catch (err) {
        view.webview.postMessage({ type: "query-error", message: String(err) });
      }
    });
    if (this.pendingQuery) {
      view.webview.postMessage({ type: "set-query", query: this.pendingQuery });
    }
  }

  public focusWithQuery(query: string): void {
    this.pendingQuery = query;
    this.view?.show?.(true);
    this.view?.webview.postMessage({ type: "set-query", query });
  }

  private renderHtml(): string {
    return `<!DOCTYPE html>
<html><body>
<style>body{font-family:var(--vscode-font-family);padding:8px}textarea{width:100%;height:110px}.btn{margin-top:8px}</style>
<textarea id="q">MATCH (f:Function) RETURN f.name AS name LIMIT 20</textarea>
<button class="btn" onclick="run()">Run Query</button>
<pre id="out"></pre>
<script>
const vscode = acquireVsCodeApi();
function run(){vscode.postMessage({type:'run-query',query:document.getElementById('q').value});}
window.addEventListener('message',e=>{const m=e.data;const out=document.getElementById('out');if(m.type==='query-result'){out.textContent=JSON.stringify(m.rows,null,2);}if(m.type==='query-error'){out.textContent='Error: '+m.message;}});
window.addEventListener('message',e=>{const m=e.data;if(m.type==='set-query'){document.getElementById('q').value=m.query;}});
</script></body></html>`;
  }
}
