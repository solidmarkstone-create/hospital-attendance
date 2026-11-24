from . import roles


def roles_ctx(request):
    u = request.user
    return {
        'role_names': sorted(roles.role_names(u)),
        'can_manage_staff': roles.can_manage_staff(u),
        'can_review': roles.can_review(u),
        'can_view_reports': roles.can_view_reports(u),
        'can_configure': roles.can_configure(u),
    }

