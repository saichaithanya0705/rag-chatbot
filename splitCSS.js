const fs = require('fs');

const rawCSS = fs.readFileSync('frontend/src/widgets/workbench-frame/workbench-frame.module.css', 'utf8');

const classMap = {
  // Chat View
  '.chatTopbar': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.messages': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.emptyState': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.inputArea': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.inputRow': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.msgInput': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.sendBtn': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.collectionLabel': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.collectionSelect': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.topbarSpacer': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.webToggleWrap': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.toggleTrack': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.toggleTrackOn': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.toggleKnob': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.offlineBadge': 'frontend/src/widgets/chat-shell/chat-view.module.css',
  '.offlineBadgeShow': 'frontend/src/widgets/chat-shell/chat-view.module.css',

  // Message Thread
  '.msg': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.msgUser': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.msgBot': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.bubble': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.thinkingBubble': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.toolCall': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.toolCallSummary': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.toolCallLabel': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.toolCallBody': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.webSearchUsed': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.citations': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.citeChip': 'frontend/src/widgets/chat-shell/message-thread.module.css',
  '.webCiteChip': 'frontend/src/widgets/chat-shell/message-thread.module.css',

  // Session Sidebar
  '.sidebar': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sidebarCollapsed': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sidebarHeader': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.newChatBtn': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.newChatPlus': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sidebarScroll': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.dateGroup': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sessionRow': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.session': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sessionActive': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',
  '.sessionDelete': 'frontend/src/widgets/chat-shell/session-sidebar.module.css',

  // Pipeline View
  '.pipelineTopbar': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.pipelineTitle': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.collectionSummary': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.pipelineBody': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.sectionLabel': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.collectionRow': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.clusterActionRow': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.colPill': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.colPillActive': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.newColBtn': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.reclusterBtn': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.reclusterBtnBusy': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.dropZone': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.dropIconSvg': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.dropTitle': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.dropSub': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileList': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileRow': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileIconSvg': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileInfo': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileName': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileMeta': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileTopicRow': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileTopicChip': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileChunkStat': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileSharedTopic': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.progWrap': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.progBar': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.progBarChunking': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.progBarEmbedding': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.progBarDone': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fstatus': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.sDone': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.sActive': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.sQueued': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',
  '.fileDel': 'frontend/src/widgets/pipeline-shell/pipeline-view.module.css',

  // Knowledge Graph
  '.graphCard': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphSvg': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphEmpty': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphLink': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphNode': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphNodeCircle': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphNodeActive': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphNodeText': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',
  '.graphHint': 'frontend/src/widgets/pipeline-shell/knowledge-graph.module.css',

  // PDF Viewer
  '.pdfPanel': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfPanelOpen': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfHeader': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfTitle': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.closeBtn': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfPageInfo': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfMock': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfPage': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  ':global(.pdf-highlight)': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css',
  '.pdfPageNum': 'frontend/src/widgets/pdf-viewer/pdf-viewer.module.css'
};

// Workbench frame keeps .app, .main, .view, .viewActive, .iconBtn, .hamburgerBtn, .hamburgerBar, .toast* and media shells
const colorsToToken = [
  ['#ffffff', 'var(--surface-base)'],
  ['#f5f5f0', 'var(--bg-canvas)'],
  ['#f1efe8', 'var(--surface-muted)'],
  ['#fafaf8', 'var(--surface-soft)'],
  ['#eeedfe', 'var(--surface-accent)'],
  ['#eeedfe', 'var(--surface-accent)'],
  ['#d3d1c7', 'var(--border-soft)'],
  ['#b4b2a9', 'var(--border-strong)'],
  ['#2c2c2a', 'var(--text-strong)'],
  ['#5f5e5a', 'var(--text-muted)'],
  ['#888780', 'var(--text-subtle-aa)'],
  ['#7f77dd', 'var(--accent)'],
  ['#534ab7', 'var(--accent-strong)'],
  ['#afa9ec', 'var(--accent-border)'],
  ['#3c3489', 'var(--accent-ink)'],
  ['#faeeda', 'var(--warning-surface)'],
  ['#854f0b', 'var(--warning-ink)'],
  ['#ef9f27', 'var(--warning)'],
  ['#1d9e75', 'var(--success)'],
  ['#0f6e56', 'var(--success-ink)'],
  ['#e24b4a', 'var(--danger)'],
  ['rgba(44, 44, 42, 0.08)', 'var(--text-subtle-aa)'], 
  ['rgba(255, 255, 255, 0.16)', 'rgba(255, 255, 255, 0.16)'],
  ['rgba(255, 255, 255, 0.12)', 'rgba(255, 255, 255, 0.12)'],
  ['rgba(238, 237, 254, 0.24)', 'rgba(238, 237, 254, 0.24)'],
  ['rgba(238, 237, 254, 0.72)', 'rgba(238, 237, 254, 0.72)'],
];

function replaceColors(cssStr) {
  let str = cssStr;
  for (const [hex, token] of colorsToToken) {
    str = str.split(hex.toLowerCase()).join(token);
    str = str.split(hex.toUpperCase()).join(token);
  }
  return str;
}

const blocks = rawCSS.split(/\n\n/); // split by blank line initially
const outputs = {
  'frontend/src/widgets/workbench-frame/workbench-frame.module.css': []
};

let currentMq = null;

const lines = rawCSS.split('\n');
let i = 0;
while(i < lines.length) {
  let line = lines[i];
  if(line.startsWith('@media')) {
    let mqBlock = [line];
    i++;
    while(i < lines.length && !lines[i].startsWith('}')) {
      // Very naive mq parsing
      mqBlock.push(lines[i]);
      i++;
    }
    if (i < lines.length) mqBlock.push(lines[i]);
    outputs['frontend/src/widgets/workbench-frame/workbench-frame.module.css'].push(mqBlock.join('\n'));
    i++;
    continue;
  }
  
  if (line.includes('{')) {
    let blockLines = [line];
    
    // gather selectors
    let selectors = line.split(/[{},]/).map(s => s.trim()).filter(s => s.startsWith('.') || s.startsWith(':global'));
    
    i++;
    while(i < lines.length && !lines[i].includes('}')) {
      blockLines.push(lines[i]);
      i++;
    }
    if (i < lines.length) blockLines.push(lines[i]); // include '}'
    
    let blockCSS = blockLines.join('\n');
    blockCSS = replaceColors(blockCSS);
    
    // find target file
    let targetFile = 'frontend/src/widgets/workbench-frame/workbench-frame.module.css';
    for(const sel of Object.keys(classMap)) {
      if (blockCSS.includes(sel + ' ') || blockCSS.includes(sel + '{') || blockCSS.includes(sel + ',') || blockCSS.includes(sel + ':')) {
        targetFile = classMap[sel];
        break;
      }
    }
    
    if(!outputs[targetFile]) {
      outputs[targetFile] = [];
    }
    outputs[targetFile].push(blockCSS);
  }
  i++;
}

// Write the files
for (const [file, cssBlocks] of Object.entries(outputs)) {
  fs.writeFileSync(file, cssBlocks.join('\n\n'));
  console.log(`Wrote ${file}`);
}
