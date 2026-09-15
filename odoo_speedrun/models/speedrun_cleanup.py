import logging

from odoo import _, api, fields, models
from odoo.modules import get_manifest
from odoo.tools.convert import convert_file

_logger = logging.getLogger(__name__)

# Records of these models are the game's own data and must NEVER be wiped or
# reloaded by the cleanup: game rooms, players, scores, profiles, chests,
# leaderboards, tournaments, etc.
SPEEDRUN_MODEL_PREFIX = 'speedrun.'
# Modules whose demo data must be preserved (they hold persistent game data).
SPEEDRUN_MODULE_PREFIX = 'speedrun'
SPEEDRUN_APP_MODULE = 'odoo_speedrun'

_TRUE_VALUES = ('True', 'true', '1')


class SpeedrunCleanup(models.Model):
    """Service model that resets the database back to its pristine demo state.

    Two phases:
      * Phase A — delete every record players created during rounds. These are
        runtime records on the business models targeted by tasks (res.partner,
        sale.order, product.template ...) that have no external id (module/demo
        data always has one) and were created, by a game's players, within that
        game's own time window.
      * Phase B — reload the demo data of every installed module (except the
        speedrun ones) so that any *modification* or *deletion* of demo records
        is reverted to the original shipped values.

    The game's own data (models prefixed ``speedrun.``) is always excluded, so
    scores, profiles, leaderboards, chests and match history survive.
    """

    _name = 'speedrun.cleanup'
    _description = 'Speedrun Data Cleanup / Demo Reset'

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @api.model
    def _icp(self):
        return self.env['ir.config_parameter'].sudo()

    @api.model
    def _is_enabled(self, key, default=True):
        val = self._icp().get_param('odoo_speedrun.%s' % key, 'True' if default else 'False')
        return val in _TRUE_VALUES

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    @api.model
    def _get_cleanable_models(self):
        """Return the business models whose player-created records may be wiped.

        Derived dynamically from the ``target_model`` of every task, so the list
        always follows the installed tasks. Speedrun's own models, transient /
        abstract / SQL-view models and models without ``create_date`` are
        excluded.
        """
        tasks = self.env['speedrun.task'].sudo().search([])
        names = {m for m in tasks.mapped('target_model') if m}
        cleanable = []
        for name in names:
            if name.startswith(SPEEDRUN_MODEL_PREFIX):
                continue
            model = self.env.get(name)
            if model is None:
                continue
            if model._transient or model._abstract or not model._auto:
                continue
            if 'create_date' not in model._fields:
                continue
            cleanable.append(name)
        return sorted(cleanable)

    # ------------------------------------------------------------------
    # Phase A — delete player creations
    # ------------------------------------------------------------------

    @api.model
    def _protected_ids(self, model_name, ids):
        """IDs (subset of ``ids``) that are module/demo data (have an xml_id)."""
        data = self.env['ir.model.data'].sudo().search([
            ('model', '=', model_name),
            ('res_id', 'in', ids),
        ])
        return set(data.mapped('res_id'))

    @api.model
    def _delete_game_creations(self, game, models_to_clean, deleted):
        """Delete records the players of ``game`` created during its lifetime.

        A record is wiped only when ALL of the following hold:
          * it lives on a business model targeted by a task (cleanable model);
          * it was created by one of this game's players;
          * it was created within the game's time window
            (``create_date`` .. ``end_time``);
          * it has no external id (module/demo data always has one).

        Scoping to the game's own time window guarantees that demo records
        (created at install time, long before any game) are never removed, even
        when they were authored by a user who later played and even when they
        lack an external id. ``deleted`` accumulates a {model: count} summary.
        """
        player_uids = game.player_ids.user_id.ids
        if not player_uids:
            return
        lo = game.start_time or game.create_date
        hi = game.end_time or fields.Datetime.now()
        domain = [
            ('create_uid', 'in', player_uids),
            ('create_date', '>=', lo),
            ('create_date', '<=', hi),
        ]
        for _pass in range(3):
            progress = False
            for model_name in models_to_clean:
                Model = self.env[model_name].sudo().with_context(active_test=False)
                try:
                    with self.env.cr.savepoint():
                        candidates = Model.search(domain)
                    if not candidates:
                        continue
                    protected = self._protected_ids(model_name, candidates.ids)
                    to_delete = candidates.filtered(lambda r: r.id not in protected)
                    if not to_delete:
                        continue
                    count = self._safe_unlink(to_delete)
                    if count:
                        deleted[model_name] = deleted.get(model_name, 0) + count
                        progress = True
                except Exception:  # noqa: BLE001
                    _logger.exception("Speedrun cleanup: error scanning model %s", model_name)
            if not progress:
                break

    @api.model
    def _delete_player_creations(self, games):
        """Delete player-created records for every game in ``games``.

        Returns a {model: count} summary. Each processed game is flagged
        ``cleanup_done`` so the cron never rescans it.
        """
        if not games:
            return {}
        models_to_clean = self._get_cleanable_models()
        deleted = {}
        for game in games:
            self._delete_game_creations(game, models_to_clean, deleted)
            game.cleanup_done = True
        return deleted

    @api.model
    def _safe_unlink(self, records):
        """Delete ``records`` defensively; returns the number actually removed.

        Tries a bulk unlink first (fast path) and falls back to per-record
        deletion under savepoints so a single blocking record (FK constraint,
        access, ...) does not abort the whole batch.
        """
        try:
            with self.env.cr.savepoint():
                records.unlink()
            return len(records)
        except Exception:  # noqa: BLE001
            pass
        removed = 0
        for rec in records:
            try:
                with self.env.cr.savepoint():
                    rec.unlink()
                removed += 1
            except Exception:  # noqa: BLE001
                _logger.debug("Speedrun cleanup: could not delete %s#%s", rec._name, rec.id)
        return removed

    # ------------------------------------------------------------------
    # Phase B — reload demo data
    # ------------------------------------------------------------------

    @api.model
    def _reload_demo_data(self):
        """Re-import the demo files of every installed module (except speedrun).

        Re-importing with ``noupdate=False`` overwrites demo records back to
        their shipped values (reverting modifications) and recreates any that
        were deleted. Each file is wrapped in a savepoint so one failing file
        does not stop the rest.
        """
        modules = self.env['ir.module.module'].sudo().search(
            [('state', '=', 'installed')], order='id')
        env = self.env(su=True, context=dict(self.env.context, install_demo=True))
        idref = {}
        reloaded = 0
        for module in modules:
            name = module.name
            if name == SPEEDRUN_APP_MODULE or name.startswith(SPEEDRUN_MODULE_PREFIX):
                continue
            try:
                manifest = get_manifest(name)
            except Exception:  # noqa: BLE001
                continue
            demo_files = list(manifest.get('demo', [])) + list(manifest.get('demo_xml', []))
            for fname in demo_files:
                try:
                    with env.cr.savepoint():
                        convert_file(env, name, fname, idref, mode='init', noupdate=False)
                    reloaded += 1
                except Exception:  # noqa: BLE001
                    _logger.warning(
                        "Speedrun cleanup: demo reload failed for %s/%s",
                        name, fname, exc_info=True)
        return reloaded

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    @api.model
    def _has_active_games(self):
        return bool(self.env['speedrun.game'].sudo().search_count(
            [('state', 'in', ('countdown', 'running'))]))

    @api.model
    def _games_to_clean(self, force=False):
        """Finished games whose player creations should be wiped.

        The cron only picks games not yet cleaned; a manual (forced) run
        re-scans every finished game (harmless — already-deleted records simply
        aren't found again).
        """
        domain = [('state', '=', 'finished')]
        if not force:
            domain.append(('cleanup_done', '=', False))
        return self.env['speedrun.game'].sudo().search(domain)

    @api.model
    def _run_reset(self, force=False):
        """Run the full reset. Returns a summary dict.

        Skips silently when a game is currently being played (unless ``force``)
        to avoid deleting records mid-round.
        """
        if not force and self._has_active_games():
            _logger.info("Speedrun cleanup skipped: a game is currently running.")
            return {'skipped': True, 'deleted': {}, 'reloaded': 0}

        games = self._games_to_clean(force=force)
        deleted = self._delete_player_creations(games)
        total_deleted = sum(deleted.values())
        _logger.info(
            "Speedrun cleanup: deleted %s player records across %s models "
            "from %s game(s)",
            total_deleted, len(deleted), len(games))

        reloaded = 0
        if self._is_enabled('cleanup_reload_demo', default=True):
            reloaded = self._reload_demo_data()
            _logger.info("Speedrun cleanup: reloaded %s demo files", reloaded)

        return {'skipped': False, 'deleted': deleted,
                'total_deleted': total_deleted, 'reloaded': reloaded}

    @api.model
    def _cron_reset_demo(self):
        """Cron entry point: reset the demo data if the feature is enabled."""
        if not self._is_enabled('cleanup_enabled', default=True):
            return
        self._run_reset(force=False)

    @api.model
    def action_reset_now(self):
        """Manual trigger (settings button). Runs even if a game is idle."""
        result = self._run_reset(force=True)
        if result.get('skipped'):
            message = _("Reset skipped: a game is currently running.")
            notif_type = 'warning'
        else:
            message = _(
                "Reset done. Deleted %(records)s player records across "
                "%(models)s models; reloaded %(demo)s demo files.",
                records=result.get('total_deleted', 0),
                models=len(result.get('deleted', {})),
                demo=result.get('reloaded', 0),
            )
            notif_type = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Speedrun Demo Reset"),
                'message': message,
                'sticky': False,
                'type': notif_type,
            },
        }
