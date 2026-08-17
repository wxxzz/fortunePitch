/**
 * 统一封装的 Axios 请求模块。
 *
 * 所有业务请求必须经由本模块发出,统一处理
 * BaseURL、API Key 注入与错误响应结构。
 */
import axios, { type AxiosInstance, type AxiosError } from 'axios'

/** 后端异常时返回的统一错误结构(成功时直接返回业务数据) */
export interface ApiErrorEnvelope {
  success: boolean
  data: null
  error: { message: string; detail: string } | null
}

/** 本地开发经 Vite 代理转发到后端 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** 开发环境使用的 API Key,与后端 Settings.API_KEY 对应 */
const API_KEY = import.meta.env.VITE_API_KEY ?? 'change-me-in-production'

const request: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 10_000,
  headers: {
    'X-API-Key': API_KEY,
  },
})

request.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorEnvelope>) => {
    const message =
      error.response?.data?.error?.message ?? error.message ?? '网络请求失败'
    return Promise.reject(new Error(message))
  },
)

export default request
