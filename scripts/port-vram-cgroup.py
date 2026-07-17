#!/usr/bin/env python3
"""Deterministic Linux 7.1+ port of pixelcluster's cgroup-aware TTM policy.

The original six commits are distributed as CachyOS' cgroup-vram aggregate.
When that aggregate no longer applies cleanly, this script performs the same
semantic changes using strict, one-match anchors instead of patch fuzz.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


class PortError(RuntimeError):
    pass


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PortError(f"required kernel source file is missing: {path}") from exc


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PortError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise PortError(f"{label}: expected exactly one semantic match, found {len(matches)}")
    match = matches[0]
    return text[: match.start()] + replacement + text[match.end() :]


TTM_ALLOC_HELPERS = r'''struct ttm_bo_alloc_state {
	/** @charge_pool: The memory pool the resource is charged to */
	struct dmem_cgroup_pool_state *charge_pool;
	/** @limit_pool: Which pool limit we should test against */
	struct dmem_cgroup_pool_state *limit_pool;
	/** @in_evict: Whether we are currently evicting buffers */
	bool in_evict;
	/**
	 * @may_try_low: Whether protected BOs may be considered after the
	 * unprotected eviction pass has failed.
	 */
	bool may_try_low;
};

/**
 * ttm_bo_alloc_at_place - attempt allocating a BO backing store in one place
 * @bo: buffer object being allocated
 * @place: requested placement
 * @ctx: operation context associated with the allocation
 * @force_space: whether eviction may be used to force space
 * @res: resulting resource on success
 * @alloc_state: cgroup charge and eviction state
 *
 * Return: 0 on success, -EBUSY when eviction should be attempted, -ENOSPC
 * when another placement should be tried, or another negative errno.
 */
static int ttm_bo_alloc_at_place(struct ttm_buffer_object *bo,
				 const struct ttm_place *place,
				 struct ttm_operation_ctx *ctx,
				 bool force_space,
				 struct ttm_resource **res,
				 struct ttm_bo_alloc_state *alloc_state)
{
	bool may_evict;
	int ret;

	may_evict = !alloc_state->in_evict && force_space &&
		    place->mem_type != TTM_PL_SYSTEM;
	if (!alloc_state->charge_pool) {
		ret = ttm_resource_try_charge(bo, place, &alloc_state->charge_pool,
					      force_space ? &alloc_state->limit_pool : NULL);
		if (ret) {
			if (ret == -EAGAIN)
				ret = may_evict ? -EBUSY : -ENOSPC;
			return ret;
		}
	}

	/*
	 * A protected allocation must be able to reclaim unprotected buffers
	 * before silently falling back to a slower memory domain. Hard-min
	 * protection may also reclaim low-only buffers; low protection first
	 * attempts an unprotected-only pass.
	 */
	if (!alloc_state->in_evict) {
		may_evict |= dmem_cgroup_below_min(NULL, alloc_state->charge_pool);
		alloc_state->may_try_low = may_evict;
		may_evict |= dmem_cgroup_below_low(NULL, alloc_state->charge_pool);
	}

	ret = ttm_resource_alloc(bo, place, res, alloc_state->charge_pool);
	if (ret) {
		if (ret == -ENOSPC && may_evict)
			ret = -EBUSY;
		return ret;
	}

	/* Ownership of the successful charge moved into the TTM resource. */
	alloc_state->charge_pool = NULL;
	return 0;
}

'''

TTM_EVICT_WALK = r'''struct ttm_bo_evict_walk {
	/** @walk: The walk base parameters. */
	struct ttm_lru_walk walk;
	/** @place: The place passed to the resource allocation. */
	const struct ttm_place *place;
	/** @evictor: The buffer object we're trying to make room for. */
	struct ttm_buffer_object *evictor;
	/** @res: The allocated resource if any. */
	struct ttm_resource **res;
	/** @evicted: Number of successful evictions. */
	unsigned long evicted;

	/** @try_low: Whether low-protected BOs may be evicted on this pass. */
	bool try_low;
	/** @hit_low: Whether the walk skipped a low-protected BO. */
	bool hit_low;
	/** @alloc_state: State associated with the allocation attempt. */
	struct ttm_bo_alloc_state *alloc_state;
};
'''

TTM_EVICT_CB = r'''static s64 ttm_bo_evict_cb(struct ttm_lru_walk *walk, struct ttm_buffer_object *bo)
{
	struct ttm_bo_evict_walk *evict_walk =
		container_of(walk, typeof(*evict_walk), walk);
	struct dmem_cgroup_pool_state *limit_pool, *ancestor = NULL;
	bool evict_valuable;
	s64 lret;

	/* Never evict from the protected allocator itself in the first pass. */
	if (!evict_walk->alloc_state->may_try_low &&
	    bo->resource->css == evict_walk->alloc_state->charge_pool)
		return 0;

	limit_pool = evict_walk->alloc_state->limit_pool;
	if (!limit_pool) {
		ancestor = dmem_cgroup_get_common_ancestor(
			bo->resource->css, evict_walk->alloc_state->charge_pool);
		limit_pool = ancestor;
	}

	evict_valuable = dmem_cgroup_state_evict_valuable(
		limit_pool, bo->resource->css, evict_walk->try_low,
		&evict_walk->hit_low);
	if (ancestor)
		dmem_cgroup_pool_state_put(ancestor);
	if (!evict_valuable)
		return 0;

	if (bo->pin_count ||
	    !bo->bdev->funcs->eviction_valuable(bo, evict_walk->place))
		return 0;

	if (bo->deleted) {
		lret = ttm_bo_wait_ctx(bo, walk->arg.ctx);
		if (!lret)
			ttm_bo_cleanup_memtype_use(bo);
	} else {
		lret = ttm_bo_evict(bo, walk->arg.ctx);
	}

	if (lret)
		goto out;

	evict_walk->evicted++;
	if (evict_walk->res)
		lret = ttm_bo_alloc_at_place(evict_walk->evictor,
					     evict_walk->place, walk->arg.ctx,
					     false, evict_walk->res,
					     evict_walk->alloc_state);
	if (lret == 0)
		return 1;
out:
	if (lret == -ENOSPC)
		return -EBUSY;
	return lret;
}
'''

TTM_EVICT_ALLOC = r'''static int ttm_bo_evict_alloc(struct ttm_device *bdev,
			      struct ttm_resource_manager *man,
			      const struct ttm_place *place,
			      struct ttm_buffer_object *evictor,
			      struct ttm_operation_ctx *ctx,
			      struct ww_acquire_ctx *ticket,
			      struct ttm_resource **res,
			      struct ttm_bo_alloc_state *state)
{
	struct ttm_bo_evict_walk evict_walk = {
		.walk = {
			.ops = &ttm_evict_walk_ops,
			.arg = {
				.ctx = ctx,
				.ticket = ticket,
			}
		},
		.place = place,
		.evictor = evictor,
		.res = res,
		.alloc_state = state,
	};
	s64 lret;

	state->in_evict = true;
	evict_walk.walk.arg.trylock_only = true;
	lret = ttm_lru_walk_for_evict(&evict_walk.walk, bdev, man, 1);

	if (!lret && evict_walk.hit_low && state->may_try_low) {
		evict_walk.try_low = true;
		lret = ttm_lru_walk_for_evict(&evict_walk.walk, bdev, man, 1);
	}
	if (lret || !ticket)
		goto out;

	evict_walk.try_low = evict_walk.hit_low = false;
	evict_walk.walk.arg.trylock_only = false;

retry:
	do {
		evict_walk.walk.arg.ticket = ticket;
		evict_walk.evicted = 0;
		lret = ttm_lru_walk_for_evict(&evict_walk.walk, bdev, man, 1);
	} while (!lret && evict_walk.evicted);

	if (!lret && evict_walk.hit_low && !evict_walk.try_low &&
	    state->may_try_low) {
		evict_walk.try_low = true;
		goto retry;
	}
out:
	state->in_evict = false;
	if (lret < 0)
		return lret;
	if (lret == 0)
		return -EBUSY;
	return 0;
}
'''

TTM_ALLOC_RESOURCE = r'''static int ttm_bo_alloc_resource(struct ttm_buffer_object *bo,
				 struct ttm_placement *placement,
				 struct ttm_operation_ctx *ctx,
				 bool force_space,
				 struct ttm_resource **res)
{
	struct ttm_device *bdev = bo->bdev;
	struct ww_acquire_ctx *ticket;
	int i, ret;

	ticket = dma_resv_locking_ctx(bo->base.resv);
	ret = dma_resv_reserve_fences(bo->base.resv, TTM_NUM_MOVE_FENCES);
	if (unlikely(ret))
		return ret;

	for (i = 0; i < placement->num_placement; ++i) {
		const struct ttm_place *place = &placement->placement[i];
		struct ttm_bo_alloc_state alloc_state = {};
		struct ttm_resource_manager *man;

		man = ttm_manager_type(bdev, place->mem_type);
		if (!man || !ttm_resource_manager_used(man))
			continue;

		if (place->flags & (force_space ? TTM_PL_FLAG_DESIRED :
				    TTM_PL_FLAG_FALLBACK))
			continue;

		ret = ttm_bo_alloc_at_place(bo, place, ctx, force_space, res,
					    &alloc_state);
		if (ret == -ENOSPC) {
			dmem_cgroup_uncharge(alloc_state.charge_pool, bo->base.size);
			dmem_cgroup_pool_state_put(alloc_state.limit_pool);
			continue;
		} else if (ret == -EBUSY) {
			ret = ttm_bo_evict_alloc(bdev, man, place, bo, ctx, ticket,
						 res, &alloc_state);
			dmem_cgroup_pool_state_put(alloc_state.limit_pool);
			if (ret) {
				dmem_cgroup_uncharge(alloc_state.charge_pool,
						     bo->base.size);
				if (ret == -EBUSY)
					continue;
				return ret;
			}
		} else if (ret) {
			dmem_cgroup_uncharge(alloc_state.charge_pool, bo->base.size);
			dmem_cgroup_pool_state_put(alloc_state.limit_pool);
			return ret;
		}

		ret = ttm_bo_add_pipelined_eviction_fences(bo, man,
						     ctx->no_wait_gpu);
		if (unlikely(ret)) {
			ttm_resource_free(bo, res);
			if (ret == -EBUSY)
				continue;
			return ret;
		}
		return 0;
	}

	return -ENOSPC;
}
'''

TTM_RESOURCE_IMPL = r'''/**
 * ttm_resource_try_charge - charge a resource manager's cgroup pool
 * @bo: buffer for which an allocation should be charged
 * @place: where the allocation is attempted
 * @ret_pool: on success, the pool that was charged
 * @ret_limit_pool: on failure, the pool responsible for the limit
 *
 * Return: 0 on charge success or a negative errno.
 */
int ttm_resource_try_charge(struct ttm_buffer_object *bo,
			    const struct ttm_place *place,
			    struct dmem_cgroup_pool_state **ret_pool,
			    struct dmem_cgroup_pool_state **ret_limit_pool)
{
	struct ttm_resource_manager *man =
		ttm_manager_type(bo->bdev, place->mem_type);

	if (!man->cg) {
		*ret_pool = NULL;
		if (ret_limit_pool)
			*ret_limit_pool = NULL;
		return 0;
	}

	return dmem_cgroup_try_charge(man->cg, bo->base.size, ret_pool,
				      ret_limit_pool);
}

int ttm_resource_alloc(struct ttm_buffer_object *bo,
		       const struct ttm_place *place,
		       struct ttm_resource **res_ptr,
		       struct dmem_cgroup_pool_state *charge_pool)
{
	struct ttm_resource_manager *man =
		ttm_manager_type(bo->bdev, place->mem_type);
	int ret;

	ret = man->func->alloc(man, bo, place, res_ptr);
	if (ret)
		return ret;

	(*res_ptr)->css = charge_pool;

	spin_lock(&bo->bdev->lru_lock);
	ttm_resource_add_bulk_move(*res_ptr, bo);
	spin_unlock(&bo->bdev->lru_lock);
	return 0;
}
EXPORT_SYMBOL_FOR_TESTS_ONLY(ttm_resource_alloc);'''

TTM_RESOURCE_DECL = r'''int ttm_resource_try_charge(struct ttm_buffer_object *bo,
			    const struct ttm_place *place,
			    struct dmem_cgroup_pool_state **ret_pool,
			    struct dmem_cgroup_pool_state **ret_limit_pool);
int ttm_resource_alloc(struct ttm_buffer_object *bo,
		       const struct ttm_place *place,
		       struct ttm_resource **res,
		       struct dmem_cgroup_pool_state *charge_pool);'''

CGROUP_COMMON_ANCESTOR = r'''
/**
 * cgroup_common_ancestor - find the common ancestor of two cgroups
 * @a: first cgroup
 * @b: second cgroup
 *
 * Return: the first common ancestor, or NULL if the cgroups are unrelated.
 */
static inline struct cgroup *cgroup_common_ancestor(struct cgroup *a,
						    struct cgroup *b)
{
	int level;

	if (a->root != b->root)
		return NULL;

	for (level = min(a->level, b->level); level >= 0; level--)
		if (a->ancestors[level] == b->ancestors[level])
			return a->ancestors[level];
	return NULL;
}
'''

DMEM_DECLARATIONS = r'''bool dmem_cgroup_below_min(struct dmem_cgroup_pool_state *root,
			   struct dmem_cgroup_pool_state *test);
bool dmem_cgroup_below_low(struct dmem_cgroup_pool_state *root,
			   struct dmem_cgroup_pool_state *test);
struct dmem_cgroup_pool_state *
dmem_cgroup_get_common_ancestor(struct dmem_cgroup_pool_state *a,
				       struct dmem_cgroup_pool_state *b);
'''

DMEM_STUBS = r'''static inline bool dmem_cgroup_below_min(struct dmem_cgroup_pool_state *root,
					 struct dmem_cgroup_pool_state *test)
{
	return false;
}

static inline bool dmem_cgroup_below_low(struct dmem_cgroup_pool_state *root,
					 struct dmem_cgroup_pool_state *test)
{
	return false;
}

static inline struct dmem_cgroup_pool_state *
dmem_cgroup_get_common_ancestor(struct dmem_cgroup_pool_state *a,
				       struct dmem_cgroup_pool_state *b)
{
	return NULL;
}

'''

DMEM_HELPERS = r'''
/**
 * dmem_cgroup_below_min - test whether usage is within effective min protection
 * @root: subtree root, or NULL for global protection
 * @test: pool whose usage is tested
 */
bool dmem_cgroup_below_min(struct dmem_cgroup_pool_state *root,
			   struct dmem_cgroup_pool_state *test)
{
	if (root == test || !pool_parent(test))
		return false;

	if (!root) {
		for (root = test; pool_parent(root); root = pool_parent(root))
			;
	}

	dmem_cgroup_calculate_protection(root, test);
	return page_counter_read(&test->cnt) <= READ_ONCE(test->cnt.emin);
}
EXPORT_SYMBOL_GPL(dmem_cgroup_below_min);

/**
 * dmem_cgroup_below_low - test whether usage is within effective low protection
 * @root: subtree root, or NULL for global protection
 * @test: pool whose usage is tested
 */
bool dmem_cgroup_below_low(struct dmem_cgroup_pool_state *root,
			   struct dmem_cgroup_pool_state *test)
{
	if (root == test || !pool_parent(test))
		return false;

	if (!root) {
		for (root = test; pool_parent(root); root = pool_parent(root))
			;
	}

	dmem_cgroup_calculate_protection(root, test);
	return page_counter_read(&test->cnt) <= READ_ONCE(test->cnt.elow);
}
EXPORT_SYMBOL_GPL(dmem_cgroup_below_low);

/**
 * dmem_cgroup_get_common_ancestor - get the common ancestor pool
 * @a: first pool
 * @b: second pool
 *
 * Return: a referenced common pool, or NULL. The caller must put it.
 */
struct dmem_cgroup_pool_state *
dmem_cgroup_get_common_ancestor(struct dmem_cgroup_pool_state *a,
				       struct dmem_cgroup_pool_state *b)
{
	struct dmem_cgroup_pool_state *pool;
	struct cgroup *ancestor_cgroup;
	struct cgroup_subsys_state *ancestor_css;

	if (!a || !b)
		return NULL;

	ancestor_cgroup = cgroup_common_ancestor(a->cs->css.cgroup,
						 b->cs->css.cgroup);
	if (!ancestor_cgroup)
		return NULL;

	ancestor_css = cgroup_e_css(ancestor_cgroup, &dmem_cgrp_subsys);
	css_get(ancestor_css);
	pool = get_cg_pool_unlocked(css_to_dmemcs(ancestor_css), a->region);
	if (IS_ERR(pool)) {
		css_put(ancestor_css);
		return NULL;
	}

	return pool;
}
EXPORT_SYMBOL_GPL(dmem_cgroup_get_common_ancestor);
'''


def port_ttm_bo(path: Path) -> None:
    text = read(path)
    if "struct ttm_bo_alloc_state" in text:
        return

    anchor = "/**\n * struct ttm_bo_evict_walk - Parameters for the evict walk.\n */\n"
    text = replace_once(text, anchor, TTM_ALLOC_HELPERS + anchor, "TTM allocation helper insertion")
    text = replace_regex_once(
        text,
        r"struct ttm_bo_evict_walk \{.*?\n\};\n(?=\nstatic s64 ttm_bo_evict_cb)",
        TTM_EVICT_WALK,
        "TTM eviction walk structure",
    )
    text = replace_regex_once(
        text,
        r"static s64 ttm_bo_evict_cb\(.*?\n\}\n(?=\nstatic const struct ttm_lru_walk_ops ttm_evict_walk_ops)",
        TTM_EVICT_CB,
        "TTM eviction callback",
    )
    text = replace_regex_once(
        text,
        r"static int ttm_bo_evict_alloc\(.*?\n\}\n(?=\n/\*\*\n \* ttm_bo_pin)",
        TTM_EVICT_ALLOC,
        "TTM eviction allocator",
    )
    text = replace_regex_once(
        text,
        r"static int ttm_bo_alloc_resource\(.*?\n\}\n(?=\n/\*\n \* ttm_bo_mem_space)",
        TTM_ALLOC_RESOURCE,
        "TTM resource allocation path",
    )
    write(path, text)


def port_ttm_resource(path: Path) -> None:
    text = read(path)
    if "int ttm_resource_try_charge(" in text:
        return
    text = replace_regex_once(
        text,
        r"int ttm_resource_alloc\(.*?EXPORT_SYMBOL_FOR_TESTS_ONLY\(ttm_resource_alloc\);",
        TTM_RESOURCE_IMPL,
        "TTM resource charge implementation",
    )
    write(path, text)


def port_ttm_header(path: Path) -> None:
    text = read(path)
    if "int ttm_resource_try_charge(" in text:
        return
    text = replace_regex_once(
        text,
        r"int ttm_resource_alloc\(struct ttm_buffer_object \*bo,\n\s*const struct ttm_place \*place,\n\s*struct ttm_resource \*\*res,\n\s*struct dmem_cgroup_pool_state \*\*ret_limit_pool\);",
        TTM_RESOURCE_DECL,
        "TTM resource declarations",
    )
    write(path, text)


def port_cgroup_header(path: Path) -> None:
    text = read(path)
    if "cgroup_common_ancestor(" in text:
        return
    pattern = (
        r"(static inline struct cgroup \*cgroup_ancestor\(struct cgroup \*cgrp,\n"
        r".*?\n\}\n)(?=\n/\*\*\n \* task_under_cgroup_hierarchy)"
    )
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise PortError(f"cgroup common-ancestor insertion: expected one anchor, found {len(matches)}")
    match = matches[0]
    text = text[: match.end()] + CGROUP_COMMON_ANCESTOR + text[match.end() :]
    write(path, text)


def port_dmem_header(path: Path) -> None:
    text = read(path)
    if "dmem_cgroup_get_common_ancestor(" in text:
        return

    decl_anchor = (
        "bool dmem_cgroup_state_evict_valuable(struct dmem_cgroup_pool_state *limit_pool,\n"
        "\t\t\t\t      struct dmem_cgroup_pool_state *test_pool,\n"
        "\t\t\t\t      bool ignore_low, bool *ret_hit_low);\n"
    )
    text = replace_once(text, decl_anchor, decl_anchor + DMEM_DECLARATIONS, "DMEM declarations")

    stub_anchor = (
        "static inline void dmem_cgroup_pool_state_put(struct dmem_cgroup_pool_state *pool)\n"
        "{ }\n"
    )
    text = replace_once(text, stub_anchor, DMEM_STUBS + stub_anchor, "DMEM disabled stubs")
    write(path, text)


def port_dmem_source(path: Path) -> None:
    text = read(path)
    if "dmem_cgroup_get_common_ancestor(" in text:
        if "css_put(ancestor_css);" not in text:
            raise PortError("existing DMEM common-ancestor implementation lacks error reference cleanup")
        return
    anchor = "EXPORT_SYMBOL_GPL(dmem_cgroup_try_charge);\n"
    text = replace_once(text, anchor, anchor + DMEM_HELPERS, "DMEM helper implementation")
    write(path, text)


def validate(tree: Path) -> None:
    checks = {
        tree / "drivers/gpu/drm/ttm/ttm_bo.c": (
            "struct ttm_bo_alloc_state",
            "dmem_cgroup_get_common_ancestor",
            "ttm_bo_alloc_at_place",
        ),
        tree / "drivers/gpu/drm/ttm/ttm_resource.c": ("ttm_resource_try_charge",),
        tree / "include/drm/ttm/ttm_resource.h": ("ttm_resource_try_charge",),
        tree / "include/linux/cgroup.h": ("cgroup_common_ancestor",),
        tree / "include/linux/cgroup_dmem.h": ("dmem_cgroup_below_min",),
        tree / "kernel/cgroup/dmem.c": (
            "dmem_cgroup_below_min",
            "dmem_cgroup_get_common_ancestor",
            "css_put(ancestor_css);",
        ),
    }
    for path, markers in checks.items():
        text = read(path)
        for marker in markers:
            if marker not in text:
                raise PortError(f"validation failed: {marker!r} is missing from {path}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: port-vram-cgroup.py /path/to/linux")
    tree = Path(sys.argv[1]).resolve()
    try:
        port_ttm_bo(tree / "drivers/gpu/drm/ttm/ttm_bo.c")
        port_ttm_resource(tree / "drivers/gpu/drm/ttm/ttm_resource.c")
        port_ttm_header(tree / "include/drm/ttm/ttm_resource.h")
        port_cgroup_header(tree / "include/linux/cgroup.h")
        port_dmem_header(tree / "include/linux/cgroup_dmem.h")
        port_dmem_source(tree / "kernel/cgroup/dmem.c")
        validate(tree)
    except PortError as exc:
        raise SystemExit(f"VRAM semantic port failed: {exc}") from exc
    print("Applied deterministic cgroup-aware VRAM port")


if __name__ == "__main__":
    main()
