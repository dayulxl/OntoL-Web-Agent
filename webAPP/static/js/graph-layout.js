// ====================================================================
// 图布局引擎 — 纯技术函数（无副作用，不操作 DOM/网络/状态）
// 依赖: LABEL_COLORS（由页面注入）
// ====================================================================

var LAYER_X = 260;
var NODE_H = 90;

// ── 工具函数 ──

function str(v) { return String(v); }

function escHtml(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escAttr(s) {
    return String(s || '').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
}

function formatMarkdown(text) {
    return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/^- (.+)$/gm, '• $1')
        .replace(/^(\d+)\. (.+)$/gm, '$1. $2')
        .replace(/\n/g, '<br>');
}

// ── 数据转换 ──

/**
 * 将图 API 返回的原始节点数组转为 nodeMap。
 * @param {Array} rawNodes — [{id, labels, properties}, ...]
 * @returns {Object} — { id: {id, labels, properties} }
 */
function _buildNodeMap(rawNodes) {
    var map = {};
    for (var i = 0; i < rawNodes.length; i++) {
        var nd = rawNodes[i];
        map[String(nd.id)] = { id: nd.id, labels: nd.labels || [], properties: nd.properties || {} };
    }
    return map;
}

/**
 * 将图 API 返回的原始边数组转为 edgeList。
 * @param {Array} rawEdges — [{edge_id, source_id, target_id, type}, ...]
 * @returns {Array} — [{source, target, type, eid}, ...]
 */
function _buildEdgeList(rawEdges) {
    var list = [];
    for (var i = 0; i < rawEdges.length; i++) {
        var e = rawEdges[i];
        list.push({
            source: String(e.source_id),
            target: String(e.target_id),
            type: e.type,
            eid: String(e.edge_id)
        });
    }
    return list;
}

// ── 有向图布局 ──

/**
 * 有向图布局算法：source(上游)放左边，target(下游)放右边。
 * 纯函数 — 不操作 DOM，不修改入参。
 *
 * @param {Object} nodeMap — { id: {id, labels, properties} }
 * @param {Array}  edgeList — [{source, target, type, eid}, ...]
 * @param {string} centerId — 中心节点 id
 * @param {number} centerX  — 中心节点 x 坐标
 * @param {number} centerY  — 中心节点 y 坐标
 * @returns {{nodes: Array, edges: Array}} — flow 格式的 {nodes, edges}
 */
function _applyDirectedLayout(nodeMap, edgeList, centerId, centerX, centerY) {
    var allNids = Object.keys(nodeMap);
    if (allNids.length === 0) return { nodes: [], edges: [] };

    var adjUp = {}, adjDown = {}, i, e;
    for (i = 0; i < allNids.length; i++) { adjUp[allNids[i]] = []; adjDown[allNids[i]] = []; }
    for (i = 0; i < edgeList.length; i++) {
        e = edgeList[i];
        if (nodeMap[e.source] && nodeMap[e.target]) {
            adjDown[e.source].push(e.target);
            adjUp[e.target].push(e.source);
        }
    }

    var colX = {}, bfsQ = [String(centerId)], visited = {};
    colX[String(centerId)] = 0;
    visited[String(centerId)] = true;
    while (bfsQ.length > 0) {
        var cur = bfsQ.shift(), j, nbr;
        for (j = 0; j < adjUp[cur].length; j++) {
            nbr = adjUp[cur][j];
            if (!visited[nbr]) { visited[nbr] = true; colX[nbr] = colX[cur] - 1; bfsQ.push(nbr); }
        }
        for (j = 0; j < adjDown[cur].length; j++) {
            nbr = adjDown[cur][j];
            if (!visited[nbr]) { visited[nbr] = true; colX[nbr] = colX[cur] + 1; bfsQ.push(nbr); }
        }
    }
    for (i = 0; i < allNids.length; i++) { if (colX[allNids[i]] === undefined) colX[allNids[i]] = 0; }

    var colGroups = {}, c;
    for (i = 0; i < allNids.length; i++) {
        c = colX[allNids[i]];
        if (!colGroups[c]) colGroups[c] = [];
        colGroups[c].push(allNids[i]);
    }

    var nodes = [], edges = [];
    var colKeys = Object.keys(colGroups).sort(function(a, b) { return parseInt(a) - parseInt(b); });
    for (var ci = 0; ci < colKeys.length; ci++) {
        var col = parseInt(colKeys[ci]);
        var nids = colGroups[col];
        var groupH = nids.length * NODE_H;
        var startY = centerY - groupH / 2 + NODE_H / 2;
        for (var k = 0; k < nids.length; k++) {
            var entry = nodeMap[nids[k]];
            var label = (entry.labels && entry.labels[0]) || 'default';
            var name = (entry.properties && entry.properties.name) || (entry.properties && entry.properties.title) || '#' + entry.id;
            var color = (typeof LABEL_COLORS !== 'undefined' && LABEL_COLORS[label]) || '#9ca18c';
            nodes.push({
                id: str(entry.id), type: 'default',
                position: { x: centerX + col * LAYER_X, y: startY + k * NODE_H },
                data: { label: name, labelType: label, props: entry.properties },
                style: { borderColor: color },
            });
        }
    }
    for (i = 0; i < edgeList.length; i++) {
        e = edgeList[i];
        if (nodeMap[e.source] && nodeMap[e.target]) {
            edges.push({
                id: e.eid, source: e.source, target: e.target,
                type: 'smoothstep', label: e.type,
                markerEnd: { type: 'arrowclosed', color: '#9ca18c' },
                style: { stroke: '#9ca18c' },
            });
        }
    }
    return { nodes: nodes, edges: edges };
}
