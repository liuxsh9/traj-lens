USER_ROLES = {"user", "system", "developer"}


def assign_groups(items):
    """Deterministic step/run projection over the flat item list (design §3.5).

    - user/system/developer message -> run_id=None, step_id=None (a "user turn")
    - assistant-side items group into runs; a run = the autonomous segment after a user turn
    - within a run, a step = one think-act-observe cycle:
        a new step starts at a `reasoning` item, or at a `function_call` that follows
        an observed `function_call_output` (a new act after observing).
    Returns a NEW list of item copies with step_id/run_id set; inputs untouched.
    """
    out = []
    run = -1
    in_user_segment = True
    step = 0
    step_has_output = False

    for it in items:
        if it.type == "message" and it.role in USER_ROLES:
            in_user_segment = True
            out.append(it.model_copy(update={"run_id": None, "step_id": None}))
            continue

        # assistant-side item (reasoning / function_call / function_call_output / assistant message)
        if in_user_segment:
            run += 1
            in_user_segment = False
            step = 0
            step_has_output = False
        else:
            if it.type == "reasoning":
                step += 1
                step_has_output = False
            elif it.type == "function_call" and step_has_output:
                step += 1
                step_has_output = False

        if it.type == "function_call_output":
            step_has_output = True

        out.append(it.model_copy(update={"run_id": run, "step_id": step}))

    return out
