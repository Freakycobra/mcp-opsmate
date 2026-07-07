import axios, { AxiosError, AxiosInstance } from 'axios';
import type { ZodSchema } from 'zod';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ApiError {
  error: string;
  detail: string | null;
  request_id: string;
  timestamp: string;
}

class ApiClient {
  public client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: `${API_BASE_URL}/api`,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.setupInterceptors();
  }

  private setupInterceptors(): void {
    // Request interceptor - inject API key
    this.client.interceptors.request.use(
      (config) => {
        const apiKey = localStorage.getItem('opsmate_api_key');
        if (apiKey) {
          config.headers['X-API-Key'] = apiKey;
        }
        // Admin endpoints need Bearer token
        if (config.url?.startsWith('/admin/')) {
          const adminToken = localStorage.getItem('opsmate_admin_token');
          if (adminToken) {
            config.headers['Authorization'] = `Bearer ${adminToken}`;
          }
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor - handle errors
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<ApiError>) => {
        if (error.response) {
          const { status, data } = error.response;

          if (status === 401) {
            this.showError('Authentication Failed', data?.detail || 'Invalid or missing API key.');
          } else if (status === 403) {
            this.showError('Access Denied', data?.detail || 'Admin privileges required.');
          } else if (status === 404) {
            this.showError('Not Found', data?.detail || 'The requested resource was not found.');
          } else if (status === 409) {
            this.showError('Conflict', data?.detail || 'The resource is in an incompatible state.');
          } else if (status === 422) {
            this.showError('Validation Error', data?.detail || 'Invalid request data.');
          } else if (status === 503) {
            this.showError('Service Unavailable', data?.detail || 'A required service is unavailable.');
          } else {
            this.showError(
              data?.error || 'Request Failed',
              data?.detail || `HTTP ${status}: An unexpected error occurred.`
            );
          }
        } else if (error.request) {
          this.showError('Connection Error', 'Unable to reach the OpsMate server. Is it running?');
        } else {
          this.showError('Request Error', error.message);
        }

        return Promise.reject(error);
      }
    );
  }

  private showError(title: string, message: string): void {
    // Dispatch a custom event that the Toast component listens for
    window.dispatchEvent(
      new CustomEvent('opsmate-toast', {
        detail: { type: 'error', title, message },
      })
    );
  }

  public async validatedGet<T>(
    url: string,
    schema: ZodSchema<T>,
    params?: Record<string, unknown>
  ): Promise<T> {
    const response = await this.client.get(url, { params });
    const parsed = schema.safeParse(response.data);
    if (!parsed.success) {
      console.warn('API response validation warning:', parsed.error.format());
      // Still return data, but log the validation issue
      return response.data as T;
    }
    return parsed.data;
  }

  public async validatedPost<T>(
    url: string,
    schema: ZodSchema<T>,
    data?: Record<string, unknown>
  ): Promise<T> {
    const response = await this.client.post(url, data);
    const parsed = schema.safeParse(response.data);
    if (!parsed.success) {
      console.warn('API response validation warning:', parsed.error.format());
      return response.data as T;
    }
    return parsed.data;
  }
}

export const apiClient = new ApiClient();
export default apiClient.client;
