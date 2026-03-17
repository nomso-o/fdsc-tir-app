import axios from "axios";

const api = axios.create({
  baseURL: "/api"
});

export const extractApiError = (error: unknown, fallback: string): string => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const message = (detail as { message?: string }).message;
      if (message && message.trim()) {
        return message;
      }
    }
    const responseMessage = error.response?.data?.message;
    if (typeof responseMessage === "string" && responseMessage.trim()) {
      return responseMessage;
    }
  }
  return fallback;
};

export default api;
