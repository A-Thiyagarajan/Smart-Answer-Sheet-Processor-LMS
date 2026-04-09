(() => {
    const MODE_KEY = 'exam_app_mode';
    const getCurrentMode = () => {
        try {
            return localStorage.getItem(MODE_KEY) || 'backend';
        } catch (e) {
            return 'backend';
        }
    };
    const isLocalMode = () => getCurrentMode() === 'local';
    const ARTIFACTS_KEY = 'local_exam_artifacts_v1';
    const REPORTS_KEY = 'local_exam_reports_v1';

    window.LOCAL_ONLY_MODE = isLocalMode();
    window.setExamAppMode = (mode) => {
        const normalized = mode === 'local' ? 'local' : 'backend';
        localStorage.setItem(MODE_KEY, normalized);
        window.LOCAL_ONLY_MODE = normalized === 'local';
        window.dispatchEvent(new CustomEvent('local-exam-store-changed'));
        return normalized;
    };

    const nowIso = () => new Date().toISOString();
    const randomId = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

    const readJson = (key, fallback) => {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (e) {
            console.warn(`Failed to read ${key}`, e);
            return fallback;
        }
    };

    const writeJson = (key, value) => {
        localStorage.setItem(key, JSON.stringify(value));
    };

    const emitChange = () => {
        window.dispatchEvent(new CustomEvent('local-exam-store-changed'));
    };

    const getArtifacts = () => readJson(ARTIFACTS_KEY, []);
    const getReports = () => readJson(REPORTS_KEY, []);
    const saveArtifacts = (artifacts) => {
        writeJson(ARTIFACTS_KEY, artifacts);
        emitChange();
    };
    const saveReports = (reports) => {
        writeJson(REPORTS_KEY, reports);
        emitChange();
    };

    const normalizeSubject = (value) => (value || '').toString().trim().toUpperCase();
    const normalizeReg = (value) => (value || '').toString().trim();

    const authFromHeaders = (headersLike) => {
        const headers = new Headers(headersLike || {});
        return {
            authorization: headers.get('Authorization') || '',
            sessionId: headers.get('X-Session-ID') || ''
        };
    };

    const parseStudentSession = (token) => {
        if (!token || !token.startsWith('local-student::')) return null;
        try {
            return JSON.parse(atob(token.split('::')[1]));
        } catch (e) {
            return null;
        }
    };

    const buildStudentSession = (payload) => {
        return `local-student::${btoa(JSON.stringify(payload))}`;
    };

    const getSessionFromRequest = (input, init) => {
        const { sessionId } = authFromHeaders(init?.headers);
        if (sessionId) return parseStudentSession(sessionId);
        const url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
        const querySession = url.searchParams.get('session');
        return parseStudentSession(querySession);
    };

    const parseRequestBody = async (init) => {
        const body = init?.body;
        if (!body) return null;
        if (typeof body === 'string') {
            try {
                return JSON.parse(body);
            } catch (e) {
                return Object.fromEntries(new URLSearchParams(body).entries());
            }
        }
        if (body instanceof FormData) return body;
        return body;
    };

    const jsonResponse = (data, status = 200) => new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json' }
    });

    const textResponse = (text, status = 200, contentType = 'text/plain') => new Response(text, {
        status,
        headers: { 'Content-Type': contentType }
    });

    const withReportCounts = (artifact) => {
        const reports = getReports();
        const activeCount = reports.filter((report) =>
            report.artifact_uuid === artifact.artifact_uuid && !report.deleted
        ).length;
        return {
            ...artifact,
            filename: artifact.original_filename,
            register_number: artifact.parsed_reg_no,
            subject_code: artifact.parsed_subject_code,
            status: artifact.workflow_status.toLowerCase(),
            report_count: activeCount
        };
    };

    const buildAuditLogs = (artifactId) => {
        const artifacts = getArtifacts();
        const artifact = artifacts.find((item) => String(item.id) === String(artifactId));
        if (!artifact) return [];

        const reports = getReports().filter((report) => report.artifact_uuid === artifact.artifact_uuid);
        const logs = [];
        reports.forEach((report) => {
            logs.push({
                id: report.id,
                action: 'report_issue',
                actor_id: report.actor_id,
                actor_username: report.actor_username,
                actor_email: report.actor_email || null,
                artifact_id: artifact.id,
                target_id: null,
                description: report.description,
                request_data: report.request_data || {},
                created_at: report.created_at
            });
            if (report.deleted) {
                logs.push({
                    id: `deleted-${report.id}`,
                    action: 'report_deleted',
                    actor_id: report.deleted_by || report.actor_id,
                    actor_username: report.deleted_by || report.actor_username,
                    artifact_id: artifact.id,
                    target_id: String(report.id),
                    description: 'Student withdrew report',
                    request_data: { target_id: String(report.id) },
                    created_at: report.deleted_at
                });
            }
            if (report.resolved) {
                logs.push({
                    id: `resolved-${report.id}`,
                    action: 'report_resolved',
                    actor_id: report.resolved_by || 'staff',
                    actor_username: report.resolved_by || 'staff',
                    artifact_id: artifact.id,
                    target_id: String(report.id),
                    description: report.resolved_note || 'Resolved by staff',
                    request_data: { resolved_report_id: report.id, note: report.resolved_note || null },
                    created_at: report.resolved_at
                });
            }
        });
        return logs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    };

    const fileToDataUrl = async (file) => {
        const buffer = await file.arrayBuffer();
        let binary = '';
        const bytes = new Uint8Array(buffer);
        const chunkSize = 0x8000;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
        }
        const base64 = btoa(binary);
        return `data:${file.type || 'application/octet-stream'};base64,${base64}`;
    };

    const localApi = {
        getArtifactViewUrl(artifactUuid, options = {}) {
            if (!isLocalMode()) {
                const session = options.sessionToken ? `?session=${encodeURIComponent(options.sessionToken)}` : '';
                return `/student/paper/${encodeURIComponent(artifactUuid)}/view${session}`;
            }
            const artifact = getArtifacts().find((item) => item.artifact_uuid === artifactUuid);
            return artifact?.data_url || 'about:blank';
        }
    };

    const originalFetch = window.fetch.bind(window);

    window.LocalExamStore = localApi;

    window.fetch = async (input, init = {}) => {
        const url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
        const pathname = url.pathname;
        const method = (init.method || 'GET').toUpperCase();

        if (!isLocalMode() || url.origin !== window.location.origin) {
            return originalFetch(input, init);
        }

        if (pathname === '/auth/staff/login' && method === 'POST') {
            const data = await parseRequestBody(init);
            const username = data?.username || 'admin';
            return jsonResponse({
                access_token: `local-staff::${username}`,
                token_type: 'bearer',
                username
            });
        }

        if (pathname === '/upload/bulk' && method === 'POST') {
            const form = await parseRequestBody(init);
            const artifacts = getArtifacts();
            const files = form instanceof FormData ? form.getAll('files') : [];
            const examSession = form instanceof FormData ? (form.get('exam_session') || 'CIA-I') : 'CIA-I';
            const results = [];

            for (const file of files) {
                if (!(file instanceof File)) continue;
                const match = file.name.match(/^(\d{12})_([A-Z0-9]{2,10})\.(pdf|jpg|jpeg|png)$/i);
                if (!match) {
                    results.push({ filename: file.name, success: false, error: 'Invalid filename format' });
                    continue;
                }

                const artifactUuid = randomId('artifact');
                const dataUrl = await fileToDataUrl(file);
                const artifact = {
                    id: artifacts.length ? Math.max(...artifacts.map((item) => item.id)) + 1 : 1,
                    artifact_uuid: artifactUuid,
                    raw_filename: file.name,
                    original_filename: file.name,
                    parsed_reg_no: normalizeReg(match[1]),
                    parsed_subject_code: normalizeSubject(match[2]),
                    exam_session: examSession,
                    file_extension: match[3].toLowerCase(),
                    mime_type: file.type || (match[3].toLowerCase() === 'pdf' ? 'application/pdf' : `image/${match[3].toLowerCase()}`),
                    uploaded_at: nowIso(),
                    submit_timestamp: null,
                    workflow_status: 'PENDING',
                    error_message: null,
                    deleted: false,
                    data_url: dataUrl
                };
                artifacts.push(artifact);
                results.push({
                    filename: file.name,
                    success: true,
                    artifact_uuid: artifactUuid,
                    parsed_register_number: artifact.parsed_reg_no,
                    parsed_subject_code: artifact.parsed_subject_code,
                    exam_session: artifact.exam_session,
                    workflow_status: artifact.workflow_status
                });
            }

            saveArtifacts(artifacts);
            return jsonResponse({
                total_files: files.length,
                successful: results.filter((item) => item.success).length,
                failed: results.filter((item) => !item.success).length,
                results
            });
        }

        if ((pathname === '/upload/all' || pathname === '/upload/list' || pathname === '/upload/' || pathname === '/upload' || pathname === '/artifacts' || pathname === '/files') && method === 'GET') {
            const artifacts = getArtifacts()
                .filter((item) => !item.deleted)
                .sort((a, b) => new Date(b.uploaded_at) - new Date(a.uploaded_at))
                .map(withReportCounts);
            return jsonResponse({ total: artifacts.length, artifacts });
        }

        if (pathname === '/auth/student/login' && method === 'POST') {
            const data = await parseRequestBody(init);
            const registerNumber = normalizeReg(data?.register_number);
            const username = (data?.username || registerNumber || 'student').toString().trim();
            if (!registerNumber) {
                return jsonResponse({ detail: 'Register number is required' }, 400);
            }
            const session = {
                session_id: buildStudentSession({
                    register_number: registerNumber,
                    username,
                    full_name: username,
                    issued_at: nowIso()
                }),
                full_name: username,
                moodle_username: username,
                moodle_user_id: Date.now()
            };
            return jsonResponse(session);
        }

        if (pathname === '/student/dashboard' && method === 'GET') {
            const session = getSessionFromRequest(input, init);
            if (!session?.register_number) {
                return jsonResponse({ detail: 'Invalid session' }, 401);
            }
            const artifacts = getArtifacts().filter((item) => !item.deleted && item.parsed_reg_no === session.register_number);
            const pending_papers = artifacts
                .filter((item) => item.workflow_status !== 'SUBMITTED_TO_MOODLE')
                .map((item) => ({
                    artifact_uuid: item.artifact_uuid,
                    subject_code: item.parsed_subject_code,
                    exam_session: item.exam_session || 'CIA-I',
                    subject_name: item.parsed_subject_code,
                    filename: item.original_filename,
                    uploaded_at: item.uploaded_at,
                    can_submit: true,
                    message: null
                }));
            const submitted_papers = artifacts
                .filter((item) => item.workflow_status === 'SUBMITTED_TO_MOODLE')
                .map((item) => ({
                    artifact_uuid: item.artifact_uuid,
                    parsed_subject_code: item.parsed_subject_code,
                    exam_session: item.exam_session || 'CIA-I',
                    original_filename: item.original_filename,
                    uploaded_at: item.uploaded_at,
                    submit_timestamp: item.submit_timestamp
                }));
            return jsonResponse({ pending_papers, submitted_papers });
        }

        const submitMatch = pathname.match(/^\/student\/submit\/([^/]+)$/);
        if (submitMatch && method === 'POST') {
            const session = getSessionFromRequest(input, init);
            if (!session?.register_number) return jsonResponse({ detail: 'Invalid session' }, 401);
            const artifacts = getArtifacts();
            const artifact = artifacts.find((item) => item.artifact_uuid === submitMatch[1] && item.parsed_reg_no === session.register_number);
            if (!artifact) return jsonResponse({ detail: 'Artifact not found' }, 404);
            artifact.workflow_status = 'SUBMITTED_TO_MOODLE';
            artifact.submit_timestamp = nowIso();
            saveArtifacts(artifacts);
            return jsonResponse({ success: true, moodle_submission_id: `LOCAL-${artifact.id}` });
        }

        const reportCreateMatch = pathname.match(/^\/student\/paper\/([^/]+)\/report$/);
        if (reportCreateMatch && method === 'POST') {
            const session = getSessionFromRequest(input, init);
            if (!session?.register_number) return jsonResponse({ detail: 'Invalid session' }, 401);
            const body = await parseRequestBody(init);
            const reports = getReports();
            reports.push({
                id: reports.length ? Math.max(...reports.map((item) => Number(item.id) || 0)) + 1 : 1,
                artifact_uuid: reportCreateMatch[1],
                actor_id: session.register_number,
                actor_username: session.username || session.register_number,
                description: body?.message || '',
                request_data: {
                    suggested_reg_no: body?.suggested_reg_no || null,
                    suggested_subject_code: body?.suggested_subject_code || null
                },
                created_at: nowIso(),
                deleted: false,
                resolved: false,
                resolved_at: null,
                resolved_by: null,
                resolved_note: null,
                deleted_at: null,
                deleted_by: null
            });
            saveReports(reports);
            return jsonResponse({ success: true, message: 'Report submitted' });
        }

        if (pathname === '/student/reports' && method === 'GET') {
            const session = getSessionFromRequest(input, init);
            if (!session?.register_number) return jsonResponse([], 401);
            const reports = getReports()
                .filter((item) => item.actor_id === session.register_number && !item.deleted)
                .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
            return jsonResponse(reports);
        }

        const reportDeleteMatch = pathname.match(/^\/student\/reports\/([^/]+)$/);
        if (reportDeleteMatch && method === 'DELETE') {
            const session = getSessionFromRequest(input, init);
            if (!session?.register_number) return jsonResponse({ detail: 'Invalid session' }, 401);
            const reports = getReports();
            const report = reports.find((item) => String(item.id) === String(reportDeleteMatch[1]) && item.actor_id === session.register_number);
            if (!report) return jsonResponse({ detail: 'Report not found' }, 404);
            report.deleted = true;
            report.deleted_at = nowIso();
            report.deleted_by = session.username || session.register_number;
            saveReports(reports);
            return jsonResponse({ success: true, message: 'Report deleted' });
        }

        const adminArtifactMatch = pathname.match(/^\/admin\/artifacts\/([^/]+)$/);
        if (adminArtifactMatch && method === 'GET') {
            const artifact = getArtifacts().find((item) => item.artifact_uuid === adminArtifactMatch[1]);
            return artifact ? jsonResponse(artifact) : jsonResponse({ detail: 'Artifact not found' }, 404);
        }

        if (adminArtifactMatch && method === 'DELETE') {
            const artifacts = getArtifacts();
            const artifact = artifacts.find((item) => item.artifact_uuid === adminArtifactMatch[1]);
            if (!artifact) return jsonResponse({ detail: 'Artifact not found' }, 404);
            artifact.deleted = true;
            artifact.workflow_status = 'DELETED';
            artifact.error_message = 'Deleted by staff';
            saveArtifacts(artifacts);
            return jsonResponse({ success: true, message: 'Artifact removed' });
        }

        const adminArtifactEditMatch = pathname.match(/^\/admin\/artifacts\/([^/]+)\/edit$/);
        if (adminArtifactEditMatch && method === 'POST') {
            const body = await parseRequestBody(init);
            const artifacts = getArtifacts();
            const artifact = artifacts.find((item) => item.artifact_uuid === adminArtifactEditMatch[1]);
            if (!artifact) return jsonResponse({ detail: 'Artifact not found' }, 404);
            artifact.parsed_reg_no = body?.parsed_reg_no ? normalizeReg(body.parsed_reg_no) : artifact.parsed_reg_no;
            artifact.parsed_subject_code = body?.parsed_subject_code ? normalizeSubject(body.parsed_subject_code) : artifact.parsed_subject_code;
            artifact.exam_session = body?.exam_session || artifact.exam_session || 'CIA-I';
            artifact.original_filename = body?.original_filename || artifact.original_filename;
            artifact.workflow_status = 'PENDING';
            artifact.submit_timestamp = null;
            artifact.error_message = null;
            saveArtifacts(artifacts);
            return jsonResponse({ success: true, message: 'Artifact updated' });
        }

        const adminResolveMatch = pathname.match(/^\/admin\/artifacts\/([^/]+)\/reports\/([^/]+)\/resolve$/);
        if (adminResolveMatch && method === 'POST') {
            const body = await parseRequestBody(init);
            const reports = getReports();
            const report = reports.find((item) => item.artifact_uuid === adminResolveMatch[1] && String(item.id) === String(adminResolveMatch[2]));
            if (!report) return jsonResponse({ detail: 'Report not found' }, 404);
            report.resolved = true;
            report.resolved_at = nowIso();
            report.resolved_by = 'staff';
            report.resolved_note = body?.note || 'Resolved by staff';
            saveReports(reports);
            return jsonResponse({ success: true, message: 'Report resolved' });
        }

        if (pathname === '/admin/audit-logs' && method === 'GET') {
            const artifactId = url.searchParams.get('artifact_id');
            return jsonResponse(buildAuditLogs(artifactId));
        }

        return originalFetch(input, init);
    };

    window.addEventListener('storage', (event) => {
        if (event.key === ARTIFACTS_KEY || event.key === REPORTS_KEY) {
            emitChange();
        }
    });

    window.addEventListener('local-exam-store-changed', () => {
        if (typeof window.loadPendingFiles === 'function' && document.getElementById('uploadSection')?.classList.contains('active')) {
            window.loadPendingFiles();
        }
        if (typeof window.loadPapers === 'function' && document.getElementById('dashboardSection')?.classList.contains('active')) {
            window.loadPapers();
        }
        if (typeof window.loadReportNotifications === 'function' && document.getElementById('dashboardSection')?.classList.contains('active')) {
            window.loadReportNotifications();
        }
    });
})();
