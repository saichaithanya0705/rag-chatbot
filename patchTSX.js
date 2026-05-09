const fs = require('fs');

function patch(filePath, newCssName, needsBase) {
  let content = fs.readFileSync(filePath, 'utf8');
  let newImport = `import styles from "./${newCssName}";`;
  if (needsBase) {
    newImport = `import baseStyles from "@/widgets/workbench-frame/workbench-frame.module.css";
import localStyles from "./${newCssName}";
const styles = { ...baseStyles, ...localStyles };`;
  }
  
  content = content.replace(/import styles from "@\/widgets\/workbench-frame\/workbench-frame\.module\.css";/, newImport);
  fs.writeFileSync(filePath, content);
  console.log('Patched', filePath);
}

patch('frontend/src/widgets/chat-shell/ChatComposer.tsx', 'chat-view.module.css', false);
patch('frontend/src/widgets/chat-shell/SessionSidebar.tsx', 'session-sidebar.module.css', false);
patch('frontend/src/widgets/chat-shell/MessageThread.tsx', 'message-thread.module.css', false);

// Wait, MessageThread uses .messages container which is in chat-view styles? Let's give it both, or wait, chat-view didn't extract 'messages' as the whole container? Yes it did.
// But the script extracted '.messages' into 'chat-view.module.css'. If MessageThread uses it, it will fail unless it imports chat-view too. Let's give it base to be safe? No, base won't have .messages.
// Let's import chat-view in MessageThread.
patch('frontend/src/widgets/chat-shell/ChatView.tsx', 'chat-view.module.css', true);
patch('frontend/src/widgets/pipeline-shell/PipelineView.tsx', 'pipeline-view.module.css', true);
patch('frontend/src/widgets/pipeline-shell/KnowledgeGraphView.tsx', 'knowledge-graph.module.css', false);
patch('frontend/src/widgets/pdf-viewer/PdfViewerPanel.tsx', 'pdf-viewer.module.css', false);

// fix MessageThread if it uses .messages.
let mtContent = fs.readFileSync('frontend/src/widgets/chat-shell/MessageThread.tsx', 'utf8');
if (mtContent.includes('styles.messages') && !mtContent.includes('chat-view')) {
  mtContent = mtContent.replace(/import styles from ".\/message-thread.module.css";/, `import threadStyles from "./message-thread.module.css";
import chatStyles from "./chat-view.module.css";
const styles = { ...threadStyles, ...chatStyles };`);
  fs.writeFileSync('frontend/src/widgets/chat-shell/MessageThread.tsx', mtContent);
}

