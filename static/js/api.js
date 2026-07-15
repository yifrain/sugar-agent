/**
 * Admin API client for Sugar Agent.
 * Handles all HTTP communication with the backend.
 */

const API_BASE = '/api/v1/admin';

const api = {
    token: '',

    setToken(token) {
        this.token = token;
    },

    async request(method, path, body = null) {
        const headers = { 'Content-Type': 'application/json' };
        if (this.token) {
            headers['X-Admin-Token'] = this.token;
        }

        const opts = { method, headers };
        if (body && method !== 'GET') {
            opts.body = JSON.stringify(body);
        }

        const url = API_BASE + path;
        const response = await fetch(url, opts);

        if (!response.ok) {
            const error = await response.text();
            throw new Error(error || `HTTP ${response.status}`);
        }

        return response.json();
    },

    // Auth
    async login(password) {
        // Simple: store password as token (the server checks it as X-Admin-Token)
        const result = await this.request('GET', '/dashboard', null);
        return result;
    },

    // Dashboard
    async getDashboard() {
        return this.request('GET', '/dashboard');
    },

    // Messages
    async getMessages(date, search, limit = 50) {
        let path = `/messages?limit=${limit}`;
        if (date) path += `&date=${date}`;
        if (search) path += `&search=${encodeURIComponent(search)}`;
        return this.request('GET', path);
    },

    async sendMessage(content) {
        return this.request('POST', '/messages/send', { content });
    },

    // Memories
    async getMemories(category, search, pinned) {
        let path = '/memories?';
        if (category) path += `category=${category}&`;
        if (search) path += `search=${encodeURIComponent(search)}&`;
        if (pinned !== undefined) path += `pinned=${pinned}&`;
        return this.request('GET', path);
    },

    async createMemory(content, category, importance) {
        return this.request('POST', '/memories', { content, category, importance });
    },

    async updateMemory(id, updates) {
        return this.request('PUT', `/memories/${id}`, updates);
    },

    async deleteMemory(id) {
        return this.request('DELETE', `/memories/${id}`);
    },

    // Prompts
    async getPrompts() {
        return this.request('GET', '/prompts');
    },

    async updatePrompt(name, content) {
        return this.request('PUT', `/prompts/${name}`, { content });
    },

    // Chat
    async chat(content) {
        return this.request('POST', '/chat', { content });
    },

    // Blood Glucose
    async getBloodGlucose(days = 30) {
        return this.request('GET', `/blood-glucose?days=${days}&limit=200`);
    },

    async addBloodGlucose(value_mmol, context, notes) {
        return this.request('POST', '/blood-glucose', { value_mmol, context, notes });
    },

    async deleteBloodGlucose(id) {
        return this.request('DELETE', `/blood-glucose/${id}`);
    },

    async getBgStats(days = 30) {
        return this.request('GET', `/blood-glucose/stats?days=${days}`);
    },

    // Scheduler
    async getSchedulerTasks() {
        return this.request('GET', '/scheduler');
    },

    async triggerTask(taskId) {
        return this.request('POST', `/scheduler/${taskId}/trigger`);
    },

    // Settings
    async getSettings() {
        return this.request('GET', '/settings');
    },
};
