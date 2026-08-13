const { St, GObject, Gio, GLib, Clutter } = imports.gi;
const Cairo = imports.cairo;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;
const Me = ExtensionUtils.getCurrentExtension();

const SCRIPT = Me.path + '/usage.py';

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
    let value = `${percent(used)}%`;
    let slots = 20 - value.length;
    let filled = Math.min(slots, Math.round(percent(used) / 5));
    return `${'█'.repeat(filled)}${'░'.repeat(slots - filled)}${value}`;
}

const ClausageIndicator = GObject.registerClass(
class ClausageIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Clausage');
        this._percent = 0;
        this._severity = 'normal';
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
        this._refreshItem = new PopupMenu.PopupMenuItem('Refresh now');
        this._refreshItem.activate = () => this._refresh();
        this.menu.addMenuItem(this._refreshItem);

        this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 60, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
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
            let [r, g, b] = ringColor(this._percent, this._severity);
            cr.setSourceRGBA(r, g, b, 1);
            cr.arc(cx, cy, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * this._percent / 100);
            cr.stroke();
        }
        cr.$dispose();
    }

    _refresh() {
        if (this._refreshing || this._destroyed) return;
        this._refreshing = true;

        try {
            this._process = new Gio.Subprocess({ argv: ['python3', SCRIPT], flags: Gio.SubprocessFlags.STDOUT_PIPE });
            this._process.init(null);
            this._process.communicate_utf8_async(null, null, (process, result) => {
                this._refreshing = false;
                this._process = null;
                if (this._destroyed) return;
                try {
                    let [, output] = process.communicate_utf8_finish(result);
                    this._render(JSON.parse(output || '{}'));
                } catch (error) {
                    this._showError();
                }
            });
        } catch (error) {
            this._refreshing = false;
            this._process = null;
            this._showError();
        }
    }

    _showError() {
        this._percent = 0;
        this._label.text = '!';
        this._usage.label.text = 'CLAUDE / USAGE\n--------------------------\nSTATUS  ERROR\nACTION  Refresh now';
        this._ring.queue_repaint();
    }

    _render(data) {
        let available = data.state === 'ok' || data.state === 'stale';
        let session = percent(data.session?.percent ?? data.five_hour?.utilization);
        let weekly = percent(data.weekly?.percent ?? data.seven_day?.utilization);
        let status = data.fresh ? 'LIVE' : data.state === 'stale' ? `CACHE / ${(data.reason || 'OFFLINE').toUpperCase()}` : (data.state || 'ERROR').toUpperCase();

        this._percent = available ? session : 0;
        this._severity = data.session?.severity || 'normal';
        this._label.text = available ? `${session}%` : '—';
        this._usage.label.text = [
            'CLAUDE / USAGE',
            '--------------------------',
            available ? `5H: [${usageBar(session)}]` : `5H: [${'░'.repeat(17)}--%]`,
            `Resets in: ${available ? data.session?.remaining ?? '--' : '--'}`,
            available ? `7D: [${usageBar(weekly)}]` : `7D: [${'░'.repeat(17)}--%]`,
            '--------------------------',
            `STATUS  ${status}`,
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
