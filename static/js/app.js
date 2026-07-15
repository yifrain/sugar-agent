/**
 * Sugar Agent Admin SPA - Main Application
 * Uses Alpine.js for reactivity and routing.
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('app', () => ({
        // === Auth ===
        authenticated: false,
        password: '',
        loginError: '',

        // === Navigation ===
        currentPage: 'dashboard',
        navItems: [
            { id: 'chat', label: '聊天测试', icon: '💬' },
            { id: 'dashboard', label: '仪表盘', icon: '📊' },
            { id: 'conversations', label: '对话记录', icon: '💬' },
            { id: 'memories', label: '记忆管理', icon: '🧠' },
            { id: 'prompts', label: '提示词编辑', icon: '✏️' },
            { id: 'bloodsugar', label: '血糖数据', icon: '📈' },
            { id: 'scheduler', label: '定时任务', icon: '⏰' },
            { id: 'settings', label: '系统设置', icon: '⚙️' },
        ],

        // === Dashboard ===
        dashboardStats: [],
        statusText: '加载中...',

        // === Conversations ===
        conversations: [],
        convSearch: '',
        convDate: '',
        convRole: '',
        convTotal: 0,
        convPage: 1,
        quickMessage: '',
        quickSending: false,
        quickReply: '',

        // === Toast ===
        toast: { show: false, message: '', type: 'success' },

        showToast(message, type = 'success') {
            this.toast = { show: true, message, type };
            setTimeout(() => { this.toast.show = false; }, 3000);
        },

        // === Chat Test ===
        chatHistory: [],
        chatInput: '',
        chatLoading: false,

        // === Memories ===
        memories: [],
        memoryCategory: '',
        memorySearch: '',
        showMemoryForm: false,
        newMemory: { content: '', category: 'fact', importance: 3 },

        // === Prompts ===
        promptFiles: [],
        selectedPrompt: 'system.md',
        promptContent: '',

        // === Blood Sugar ===
        bgReadings: [],
        bgStats: null,
        newBg: { value_mmol: '', context: '', notes: '' },
        bgChart: null,

        // === Scheduler ===
        schedulerTasks: [],
        schedulerHistory: [],

        // === Settings ===
        settings: {},

        // === Init ===
        async init() {
            // Check if token is stored
            const savedToken = localStorage.getItem('sugar_admin_token');
            if (savedToken) {
                api.setToken(savedToken);
                try {
                    await this.loadDashboard();
                    this.authenticated = true;
                    this.startAutoRefresh();
                } catch (e) {
                    localStorage.removeItem('sugar_admin_token');
                }
            }
        },

        startAutoRefresh() {
            setInterval(() => {
                if (this.authenticated) {
                    this.loadDashboard();
                }
            }, 30000); // Refresh every 30s
        },

        // === Auth ===
        async login() {
            this.loginError = '';
            api.setToken(this.password);
            try {
                await api.getDashboard();
                this.authenticated = true;
                localStorage.setItem('sugar_admin_token', this.password);
                this.password = '';
                await this.loadDashboard();
                this.startAutoRefresh();
            } catch (e) {
                this.loginError = '登录失败，请检查密码';
                api.setToken('');
            }
        },

        logout() {
            this.authenticated = false;
            localStorage.removeItem('sugar_admin_token');
            api.setToken('');
        },

        // === Navigation ===
        navigate(page) {
            this.currentPage = page;
            switch (page) {
                case 'chat':
                    // nothing special to load
                    setTimeout(() => this.scrollChat(), 100);
                    break;
                case 'dashboard':
                    this.loadDashboard();
                    break;
                case 'conversations':
                    this.convPage = 1;
                    this.loadConversations();
                    break;
                case 'memories':
                    this.loadMemories();
                    break;
                case 'prompts':
                    this.loadPrompts();
                    break;
                case 'bloodsugar':
                    this.loadBloodSugar();
                    break;
                case 'scheduler':
                    this.loadScheduler();
                    break;
                case 'settings':
                    this.loadSettings();
                    break;
            }
        },

        // === Dashboard ===
        async loadDashboard() {
            try {
                const data = await api.getDashboard();
                this.dashboardStats = [
                    { label: '今日消息', value: data.messages_today },
                    { label: '今日血糖记录', value: data.bg_readings_today },
                    { label: '本周血糖记录', value: data.bg_readings_week },
                    { label: '总记忆数', value: data.total_memories },
                    { label: '今日Token用量', value: data.llm_tokens_today },
                    { label: '活跃定时任务', value: data.active_tasks },
                    { label: '桥接状态', value: data.bridge_connected ? '🟢 正常' : '🔴 断开' },
                ];
                this.statusText = `桥接: ${data.bridge_connected ? '🟢' : '🔴'} | 消息: ${data.messages_today}`;
            } catch (e) {
                console.error('Dashboard load failed:', e);
            }
        },

        // === Conversations ===
        async loadConversations(append = false) {
            try {
                const limit = 50;
                const offset = append ? (this.convPage - 1) * limit : 0;
                const data = await api.getMessages(this.convDate || null, this.convSearch || null, this.convRole || null, limit, offset);
                this.conversations = append ? [...this.conversations, ...(data.messages || [])] : (data.messages || []);
                this.convTotal = data.total || this.conversations.length;
            } catch (e) {
                console.error('Conversations load failed:', e);
            }
        },

        async sendQuickMessage() {
            const content = this.quickMessage.trim();
            if (!content || this.quickSending) return;
            this.quickSending = true;
            this.quickReply = '';
            try {
                const result = await api.chat(content);
                this.quickReply = result.reply || '(无回复)';
                this.quickMessage = '';
                // Refresh the conversation list
                setTimeout(() => this.loadConversations(), 500);
            } catch (e) {
                this.showToast('发送失败: ' + e.message, 'error');
            } finally {
                this.quickSending = false;
            }
        },

        // === Chat Test ===
        async sendChat() {
            const content = this.chatInput.trim();
            if (!content || this.chatLoading) return;
            this.chatHistory.push({ role: 'user', content });
            this.chatInput = '';
            this.chatLoading = true;
            setTimeout(() => this.scrollChat(), 50);
            try {
                const result = await api.chat(content);
                this.chatHistory.push({ role: 'agent', content: result.reply || '(无回复)' });
            } catch (e) {
                this.chatHistory.push({ role: 'agent', content: '😢 发送失败: ' + e.message });
            } finally {
                this.chatLoading = false;
                setTimeout(() => this.scrollChat(), 50);
            }
        },

        scrollChat() {
            const el = document.getElementById('chatMessages');
            if (el) el.scrollTop = el.scrollHeight;
        },

        // === Memories ===
        async loadMemories() {
            try {
                const data = await api.getMemories(this.memoryCategory || null, this.memorySearch || null);
                this.memories = data.memories || [];
            } catch (e) {
                console.error('Memories load failed:', e);
            }
        },

        async createMemory() {
            if (!this.newMemory.content.trim()) return;
            try {
                await api.createMemory(this.newMemory.content, this.newMemory.category, this.newMemory.importance);
                this.newMemory = { content: '', category: 'fact', importance: 3 };
                this.showMemoryForm = false;
                await this.loadMemories();
            } catch (e) {
                this.showToast('创建失败: ' + e.message, 'error');
            }
        },

        async togglePin(mem) {
            try {
                await api.updateMemory(mem.id, { is_pinned: !mem.is_pinned });
                await this.loadMemories();
            } catch (e) {
                this.showToast('操作失败: ' + e.message, 'error');
            }
        },

        async deleteMemory(id) {
            if (!confirm('确定删除这条记忆？')) return;
            try {
                await api.deleteMemory(id);
                await this.loadMemories();
            } catch (e) {
                this.showToast('删除失败: ' + e.message, 'error');
            }
        },

        // === Prompts ===
        async loadPrompts() {
            try {
                const data = await api.getPrompts();
                this.promptFiles = Object.keys(data.files);
                if (this.promptFiles.length > 0) {
                    this.selectedPrompt = this.promptFiles[0];
                    this.promptContent = data.files[this.selectedPrompt] || '';
                }
            } catch (e) {
                console.error('Prompts load failed:', e);
            }
        },

        async loadPrompt() {
            try {
                const data = await api.getPrompts();
                this.promptContent = data.files[this.selectedPrompt] || '';
            } catch (e) {
                console.error('Prompt load failed:', e);
            }
        },

        async savePrompt() {
            try {
                await api.updatePrompt(this.selectedPrompt, this.promptContent);
                this.showToast('提示词已保存！备份文件已创建 ✅');
            } catch (e) {
                this.showToast('保存失败: ' + e.message, 'error');
            }
        },

        // === Blood Sugar ===
        async loadBloodSugar() {
            try {
                const [readingsData, statsData] = await Promise.all([
                    api.getBloodGlucose(30),
                    api.getBgStats(30),
                ]);
                this.bgReadings = readingsData.readings || [];
                this.bgStats = statsData;
                this.renderBgChart();
            } catch (e) {
                console.error('Blood sugar load failed:', e);
            }
        },

        renderBgChart() {
            const canvas = document.getElementById('bgChart');
            if (!canvas || this.bgReadings.length === 0) return;

            if (this.bgChart) {
                this.bgChart.destroy();
            }

            const sorted = [...this.bgReadings].reverse();
            const labels = sorted.map(r => {
                const d = new Date(r.recorded_at);
                return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
            });
            const values = sorted.map(r => r.value_mmol);

            this.bgChart = new Chart(canvas, {
                type: 'line',
                data: {
                    labels,
                    datasets: [{
                        label: '血糖 (mmol/L)',
                        data: values,
                        borderColor: 'rgb(236, 72, 153)',
                        backgroundColor: 'rgba(236, 72, 153, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        pointBackgroundColor: values.map(v =>
                            v < 3.9 ? 'rgb(239, 68, 68)' :
                            v > 10.0 ? 'rgb(249, 115, 22)' :
                            'rgb(34, 197, 94)'
                        ),
                    }],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        annotation: {
                            annotations: {
                                lowLine: { type: 'line', yMin: 3.9, yMax: 3.9, borderColor: 'red', borderWidth: 1, borderDash: [5,5] },
                                highLine: { type: 'line', yMin: 10.0, yMax: 10.0, borderColor: 'orange', borderWidth: 1, borderDash: [5,5] },
                            }
                        }
                    },
                    scales: {
                        y: {
                            min: 0,
                            max: Math.max(20, Math.max(...values) + 2),
                            title: { display: true, text: 'mmol/L' },
                        },
                        x: {
                            ticks: { maxTicksLimit: 15 },
                        },
                    },
                },
            });
        },

        async addBgReading() {
            if (!this.newBg.value_mmol) return;
            try {
                await api.addBloodGlucose(
                    parseFloat(this.newBg.value_mmol),
                    this.newBg.context || null,
                    this.newBg.notes || null
                );
                this.newBg = { value_mmol: '', context: '', notes: '' };
                await this.loadBloodSugar();
            } catch (e) {
                this.showToast('添加失败: ' + e.message, 'error');
            }
        },

        async deleteBgReading(id) {
            if (!confirm('确定删除这条血糖记录？')) return;
            try {
                await api.deleteBloodGlucose(id);
                await this.loadBloodSugar();
            } catch (e) {
                this.showToast('删除失败: ' + e.message, 'error');
            }
        },

        getBgColor(value) {
            if (value < 3.0) return 'text-red-600 font-bold';
            if (value < 3.9) return 'text-red-500';
            if (value > 16.0) return 'text-red-600 font-bold';
            if (value > 10.0) return 'text-orange-500';
            if (value >= 3.9 && value <= 7.0) return 'text-green-500';
            return 'text-gray-700';
        },

        // === Scheduler ===
        async loadScheduler() {
            try {
                const data = await api.getSchedulerTasks();
                const oldTasks = this.schedulerTasks || [];
                this.schedulerTasks = (data.tasks || []).map(t => {
                    const old = oldTasks.find(o => o.id === t.id);
                    return { ...t, _preview: old?._preview || '' };
                });
                this.schedulerHistory = data.history || [];
            } catch (e) {
                console.error('Scheduler load failed:', e);
            }
        },

        async triggerTask(taskId) {
            try {
                const result = await api.triggerTask(taskId);
                const task = this.schedulerTasks.find(t => t.id === taskId);
                if (task) {
                    task._preview = result.message || '(未生成消息)';
                }
                this.showToast('预览已生成 ✅');
            } catch (e) {
                this.showToast('触发失败: ' + e.message, 'error');
            }
        },

        async updateTaskTime(taskId, field, value) {
            const v = parseInt(value);
            if (isNaN(v)) return;
            try {
                const body = field === 'hour' ? { cron_hour: v } : { cron_minute: v };
                await api.updateSchedulerTask(taskId, body);
                this.showToast('时间已更新 ✅');
                setTimeout(() => this.loadScheduler(), 500);
            } catch (e) {
                this.showToast('更新失败: ' + e.message, 'error');
            }
        },

        async toggleTask(task) {
            try {
                await api.updateSchedulerTask(task.id, { enabled: !task.enabled });
                this.showToast(task.enabled ? '已暂停' : '已启用');
                setTimeout(() => this.loadScheduler(), 500);
            } catch (e) {
                this.showToast('操作失败: ' + e.message, 'error');
            }
        },

        // === Settings ===
        async loadSettings() {
            try {
                this.settings = await api.getSettings();
            } catch (e) {
                console.error('Settings load failed:', e);
            }
        },

        // === Utilities ===
        formatTime(ts) {
            if (!ts) return '未知';
            const d = new Date(ts);
            const now = new Date();
            const diff = now - d;
            if (diff < 60000) return '刚刚';
            if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
            if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
            return d.toLocaleString('zh-CN', {
                month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit'
            });
        },
    }));
});
