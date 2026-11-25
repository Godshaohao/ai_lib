"""ai_lib_qor: artifact-oriented library quality tools (package composition root)."""
from ai_lib_qor.versions.runtime import register_hook


def _wire_default_hooks() -> None:
    """Register lazy default hooks at package composition root so lower layers stay strict DAG."""

    def _legacy_post_inventory(work, result, **kwargs):
        from ai_lib_qor.application.path_refresh import _complete_legacy_build
        return _complete_legacy_build(work, result, **kwargs)

    def _render_excel_from_check(work, vendor, library, check_filename, excel_path=None):
        from ai_lib_qor.reporting.check_renderer import render_excel_from_check
        return render_excel_from_check(work, vendor, library, check_filename, excel_path=excel_path)

    def _render_overall_excel_from_saved(work, vendor, library, overall_filename, excel_path=None):
        from ai_lib_qor.reporting.check_renderer import render_overall_excel_from_saved
        return render_overall_excel_from_saved(work, vendor, library, overall_filename, excel_path=excel_path)

    def _render_overall_excel_rows(work, vendor, library, rows, excel_path, *, business_ip=None, ip_type=None):
        from ai_lib_qor.reporting.check_renderer import render_overall_excel_rows
        return render_overall_excel_rows(
            work,
            vendor,
            library,
            rows,
            excel_path,
            business_ip=business_ip,
            ip_type=ip_type,
        )

    register_hook('sources.post_inventory', _legacy_post_inventory)
    register_hook('reporting.render_excel_from_check', _render_excel_from_check)
    register_hook('reporting.render_overall_excel_from_saved', _render_overall_excel_from_saved)
    register_hook('reporting.render_overall_excel_rows', _render_overall_excel_rows)


_wire_default_hooks()
