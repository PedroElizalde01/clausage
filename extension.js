const { St, GObject, Gio, GLib, Clutter } = imports.gi;
const Cairo = imports.cairo;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();

const SCRIPT = Me.path + '/usage.py';

// The usage endpoint rate limits aggressive callers. Poll gently and back off on
// failure so a transient 429 cannot become a permanent one.
const POLL_INTERVAL = 300;
const POLL_MAX_INTERVAL = 3600;
const STALE_RING = [0.59, 0.59, 0.59];

const REASON_LABEL = {
    auth: 'AUTH EXPIRED',
    network: 'OFFLINE',
    rate: 'RATE LIMITED',
    api: 'API ERROR',
};

function percent(value) {
    let result = Math.round(Number(value));
    return Number.isFinite(result) ? Math.max(0, Math.min(result, 100)) : 0;
}

function ringColor(used, severity) {
    if (severity === 'error' || severity === 'critical' || used > 85) return [0.94, 0.27, 0.27];
    if (used >= 50) return [0.95, 0.77, 0.06];
    return [0.21, 0.78, 0.47];
}

function usageBar(used) {
    if (used === null || used === undefined) return `${'░'.repeat(17)} --%`;
    let value = ` ${percent(used)}%`;
    let slots = 21 - value.length;
    let filled = Math.min(slots, Math.round(percent(used) / 5));
    return `${'█'.repeat(filled)}${'░'.repeat(slots - filled)}${value}`;
}

function reasonLabel(reason) {
    return REASON_LABEL[reason] || String(reason || 'ERROR').toUpperCase();
}

function cacheAge(fetchedAt) {
    let seconds = Math.floor(Date.now() / 1000 - Number(fetchedAt));
    if (!Number.isFinite(seconds)) return '?';
    seconds = Math.max(0, seconds);
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m old`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h old`;
    return `${Math.floor(seconds / 86400)}d old`;
}

function statusLine(data) {
    if (data.fresh) return 'LIVE';
    if (data.state === 'stale') return `CACHE ${cacheAge(data.fetched_at)} / ${reasonLabel(data.reason)}`;
    return reasonLabel(data.state);
}

// A cached reading is void once its window has reset: usage returns to zero at
// rollover, so the stored number is known to be wrong rather than merely old.
function reading(window, available, fresh) {
    if (!available) return null;
    if (!fresh && window?.expired) return null;
    return percent(window?.percent);
}

function nextDelay(delay, data) {
    if (data.fresh) return POLL_INTERVAL;
    let wanted = Number(data.retry_after) || delay * 2;
    return Math.min(Math.max(wanted, POLL_INTERVAL), POLL_MAX_INTERVAL);
}

const ClausageIndicator = GObject.registerClass(
class ClausageIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Clausage');
        this._percent = 0;
        this._severity = 'normal';
        this._fresh = true;
        this._delay = POLL_INTERVAL;
        this._refreshing = false;
        this._destroyed = false;
        this._process = null;

        this._box = new St.BoxLayout({ style_class: 'panel-status-menu-box' });
        this._ring = new St.DrawingArea({ width: 16, height: 16, y_align: Clutter.ActorAlign.CENTER, style: 'margin-right: 6px;' });
        this._ring.connect('repaint', area => this._drawRing(area));
        this._label = new St.Label({ text: '—', y_align: Clutter.ActorAlign.CENTER });
        this._box.add_child(this._ring);
        this._box.add_child(this._label);
        this.add_child(this._box);

        this._usage = new PopupMenu.PopupMenuItem('CLAUDE / USAGE\n--------------------------\nSTATUS  LOADING', { reactive: false });
        this._usage.label.style = 'font-family: monospace;';
        this.menu.addMenuItem(this._usage);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._refreshItem = new PopupMenu.PopupMenuItem('[ REFRESH NOW ]');
        this._refreshItem.label.style = 'font-family: monospace;';
        this._refreshItem.activate = () => this._refresh();
        this.menu.addMenuItem(this._refreshItem);

        this._refresh();
    }

    _drawRing(area) {
        let cr = area.get_context();
        let [w, h] = area.get_surface_size();
        let cx = w / 2, cy = h / 2, radius = Math.min(w, h) / 2 - 2;
        cr.setLineWidth(2.4);
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.setSourceRGBA(1, 1, 1, 0.28);
        cr.arc(cx, cy, radius, 0, Math.PI * 2);
        cr.stroke();
        if (this._percent > 0) {
            let [r, g, b] = this._fresh ? ringColor(this._percent, this._severity) : STALE_RING;
            cr.setSourceRGBA(r, g, b, 1);
            cr.arc(cx, cy, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * this._percent / 100);
            cr.stroke();
        }
        cr.$dispose();
    }

    _scheduleNext() {
        if (this._destroyed) return;
        if (this._timer) GLib.Source.remove(this._timer);
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, this._delay, () => {
            this._timer = 0;
            this._refresh();
            return GLib.SOURCE_REMOVE;
        });
    }

    _refresh() {
        if (this._destroyed) return;
        if (this._refreshing) {
            this._scheduleNext();
            return;
        }
        this._refreshing = true;
        this._refreshItem.label.text = '[ REFRESHING… ]';

        try {
            this._process = new Gio.Subprocess({ argv: ['python3', SCRIPT], flags: Gio.SubprocessFlags.STDOUT_PIPE });
            this._process.init(null);
            this._process.communicate_utf8_async(null, null, (process, result) => {
                this._refreshing = false;
                this._process = null;
                if (this._destroyed) return;
                this._refreshItem.label.text = '[ REFRESH NOW ]';
                let data = {};
                try {
                    let [, output] = process.communicate_utf8_finish(result);
                    data = JSON.parse(output || '{}');
                    this._render(data);
                } catch (error) {
                    this._showError();
                }
                this._delay = nextDelay(this._delay, data);
                this._scheduleNext();
            });
        } catch (error) {
            this._refreshing = false;
            this._process = null;
            this._refreshItem.label.text = '[ REFRESH NOW ]';
            this._showError();
            this._delay = nextDelay(this._delay, {});
            this._scheduleNext();
        }
    }

    _showError() {
        this._percent = 0;
        this._fresh = false;
        this._label.text = '!';
        this._usage.label.text = 'CLAUDE / USAGE\n--------------------------\nSTATUS  ERROR\nACTION  Refresh now';
        this._ring.queue_repaint();
    }

    _render(data) {
        let available = data.state === 'ok' || data.state === 'stale';
        let fresh = Boolean(data.fresh);
        let session = reading(data.session ?? { percent: data.five_hour?.utilization }, available, fresh);
        let weekly = reading(data.weekly ?? { percent: data.seven_day?.utilization }, available, fresh);

        this._percent = session ?? 0;
        this._fresh = fresh;
        this._severity = data.session?.severity || 'normal';
        this._label.text = session === null ? '—' : `${session}%`;
        this._usage.label.text = [
            'CLAUDE / USAGE',
            '--------------------------',
            `5H: [${usageBar(session)}]`,
            `Resets in: ${session === null ? '--' : data.session?.remaining ?? '--'}`,
            `7D: [${usageBar(weekly)}]`,
            '--------------------------',
            `STATUS  ${statusLine(data)}`,
        ].join('\n');
        this._ring.queue_repaint();
    }

    destroy() {
        this._destroyed = true;
        if (this._timer) GLib.Source.remove(this._timer);
        this._timer = 0;
        try { this._process?.force_exit(); } catch (error) {}
        this._process = null;
        super.destroy();
    }
});

let indicator;
function init() {}
function enable() { indicator = new ClausageIndicator(); Main.panel.addToStatusArea('clausage', indicator); }
function disable() { if (indicator) { indicator.destroy(); indicator = null; } }
