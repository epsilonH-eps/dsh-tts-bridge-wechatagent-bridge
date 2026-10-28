// 朗读桥 -> 微信语音条：DSH 工具半边。
// 只负责在当前微信会话里暴露一个工具；真正的录音、SILK 和原生发送在 bridge.py。
import { spawn } from 'node:child_process'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const PYTHON = join(ROOT, '.venv', 'Scripts', 'python.exe')
const WECHAT_ROOT = process.env.WECHATAGENT_ROOT || 'D:\\WeChatAgent\\data\\workspace'

export const name = 'wechat-voice'
export const inject = ['tools']

const textOutput = {
  schema: { type: 'object', properties: {}, additionalProperties: true },
  render: (_args, value) => [{
    type: 'text',
    text: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
  }],
}

function sessionIdOf(session) {
  if (!session || typeof session !== 'object') return ''
  for (const key of ['id', 'sessionId']) {
    if (typeof session[key] === 'string') return session[key]
  }
  return ''
}

function sessionIdFromExec(exec) {
  try {
    const agent = exec && (exec.agent || exec.caller || exec.agentRef)
    if (agent && agent.session) return sessionIdOf(agent.session)
    if (agent && typeof agent === 'object') {
      for (const key of ['sessionId', 'id']) if (typeof agent[key] === 'string') return agent[key]
    }
  } catch (error) {}
  return ''
}

/** social-... 会话 -> wechat:private:<id>；映射来自 WeChatAgent 自己的 dsh-sessions.json。 */
export function chatForSession(sessionId) {
  if (!sessionId) return ''
  const accounts = join(WECHAT_ROOT, 'state', 'accounts')
  if (!existsSync(accounts)) return ''
  for (const name of readdirSync(accounts)) {
    const file = join(accounts, name, 'dsh-sessions.json')
    if (!existsSync(file)) continue
    try {
      const data = JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, ''))
      const conversations = data && data.conversations
      if (!conversations || typeof conversations !== 'object') continue
      for (const [chat, mapped] of Object.entries(conversations)) {
        if (String(mapped) === String(sessionId)) return chat
      }
    } catch (error) {}
  }
  return ''
}

function runBridge(text, chat, maxSeconds) {
  return new Promise((resolve) => {
    if (!existsSync(PYTHON)) {
      resolve({ ok: false, error: '插件的 Python 环境不存在：' + PYTHON })
      return
    }
    const args = [
      join(ROOT, 'lib', 'bridge.py'),
      '--text', text,
      '--chat', chat,
      '--wechat-root', WECHAT_ROOT,
      '--max-seconds', String(maxSeconds),
    ]
    const child = spawn(PYTHON, args, { cwd: ROOT, windowsHide: true })
    let out = ''
    let err = ''
    let done = false
    const finish = (value) => { if (!done) { done = true; resolve(value) } }
    const timer = setTimeout(() => {
      try { child.kill() } catch (error) {}
      finish({ ok: false, error: '朗读桥发送超时（90 秒）' })
    }, 90000)
    child.stdout.on('data', (data) => { out += data.toString('utf8') })
    child.stderr.on('data', (data) => { err += data.toString('utf8') })
    child.on('error', (error) => { clearTimeout(timer); finish({ ok: false, error: String(error.message || error) }) })
    child.on('close', () => {
      clearTimeout(timer)
      const lines = out.trim().split(/\r?\n/).filter(Boolean)
      for (let i = lines.length - 1; i >= 0; i--) {
        try {
          const parsed = JSON.parse(lines[i])
          if (parsed && typeof parsed === 'object') { finish(parsed); return }
        } catch (error) {}
      }
      finish({ ok: false, error: (err || out || 'bridge.py 没有返回 JSON').slice(-1200) })
    })
  })
}

export async function apply(ctx) {
  ctx.tools.register({
    name: 'wechat_voice_send',
    description:
      '把一段话通过「朗读桥」念出来，录成真正的微信语音条，发到当前微信聊天。'
      + '你可以在自己觉得“这句话用声音说更合适”时主动调用，不必等本人明确要求；'
      + '适合短句、情绪、晚安/安抚/撒娇/提醒、想让他听见你声音的时候。'
      + '普通信息、长文、代码、链接仍优先用文字；一次回复最多发一条语音，不要连续刷语音。'
      + '会先让 Edge 里的朗读桥念这段话（需要 chat.deepseek.com 页面开着并登录），再录制系统声音发送。'
      + '发送是微信原生语音消息，不是文件。',
    parameters: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: '要念出来并发到微信的文字；建议 1~200 字，太长会超过单条语音时长。',
        },
        maxSeconds: {
          type: 'number',
          description: '最长录制秒数，默认 35；一般不用填。',
        },
      },
      required: ['text'],
      additionalProperties: false,
    },
    output: textOutput,
    async execute(args, exec) {
      const text = String(args?.text || '').trim()
      if (!text) return { ok: false, error: '缺少要念的文字' }
      if (text.length > 500) return { ok: false, error: '文字太长，单条微信语音请控制在 500 字以内' }
      const sessionId = sessionIdFromExec(exec)
      const chat = chatForSession(sessionId)
      if (!chat) {
        return { ok: false, error: '当前不在 WeChatAgent 的微信会话里，找不到要发送的微信聊天。' }
      }
      const maxSeconds = Math.max(12, Math.min(Number(args?.maxSeconds) || 35, 60))
      const result = await runBridge(text, chat, maxSeconds)
      return result
    },
  })
}
