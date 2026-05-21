// FastRabbit API 模块 — 所有后端调用的封装
const API = '/api';

async function api(method, path, body) {
  const opts = { method, headers: body ? {'Content-Type':'application/json'} : {} };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API}${path}`, opts);
  return res.json();
}

const $ = {
  projects: {
    list:     ()             => api('GET', '/projects'),
    get:      (name)         => api('GET', `/projects/${name}`),
    create:   (name, script) => api('POST', '/projects', {name, script_text:script||''}),
    del:      (name)         => api('DELETE', `/projects/${name}`),
    sync:     (name)         => api('POST', `/projects/${name}/sync`),
    script:   {
      get:    (name) => api('GET', `/projects/${name}/script`),
      upload: (name, text) => api('POST', `/projects/${name}/upload-script`, {script_text:text}),
    },
    episodes: (name) => api('GET', `/projects/${name}/episodes`),
    scenes:   (name, ep) => api('GET', `/projects/${name}/episodes/${ep}/scenes`),
    shots:    (name, ep, sc) => api('GET', `/projects/${name}/episodes/${ep}/scenes/${sc}/shots`),
    assets: {
      characters: (name) => api('GET', `/projects/${name}/assets/characters`),
      scenes:     (name) => api('GET', `/projects/${name}/assets/scenes`),
      shots:      (name) => api('GET', `/projects/${name}/assets/shots`),
    },
  },
  pipeline: {
    run: (name, step, params='') => api('POST', `/projects/${name}/pipeline/${step}${params?'?'+params:''}`),
    taskStatus: (name, taskId) => api('GET', `/projects/${name}/pipeline/task-status/${taskId}`),
    videoStatus: (name, taskId) => api('GET', `/projects/${name}/pipeline/video-status/${taskId}`),
  },
};

function assetUrl(name, relPath) {
  return `${API}/projects/${name}/files/${relPath}`;
}

// 步骤名称映射
const STEP_NAMES = ['', '剧本拆解', '场次拆镜头', '角色设定', '角色立绘图', '场景提示词', '场景图', '镜头视频'];
