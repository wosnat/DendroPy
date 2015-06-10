#! /usr/bin/env python

##############################################################################
##  DendroPy Phylogenetic Computing Library.
##
##  Copyright 2010-2014 Jeet Sukumaran and Mark T. Holder.
##  All rights reserved.
##
##  See "LICENSE.txt" for terms and conditions of usage.
##
##  If you use this work or any portion thereof in published work,
##  please cite it as:
##
##     Sukumaran, J. and M. T. Holder. 2010. DendroPy: a Python library
##     for phylogenetic computing. Bioinformatics 26: 1569-1571.
##
##############################################################################

"""
Models, modeling and model-fitting of birth-death processes.
"""

import sys
import math
import collections
import itertools
from dendropy.calculate import probability
from dendropy.utility import GLOBAL_RNG
from dendropy.utility.error import TreeSimTotalExtinctionException
from dendropy.utility import constants

import dendropy

def birth_death_tree(birth_rate, death_rate, birth_rate_sd=0.0, death_rate_sd=0.0, **kwargs):
    """
    Returns a birth-death tree with birth rate specified by ``birth_rate``, and
    death rate specified by ``death_rate``, with edge lengths in continuous (real)
    units.

    ``birth_rate_sd`` is the standard deviation of the normally-distributed mutation
    added to the birth rate as it is inherited by daughter nodes; if 0, birth
    rate does not evolve on the tree.

    ``death_rate_sd`` is the standard deviation of the normally-distributed mutation
    added to the death rate as it is inherited by daughter nodes; if 0, death
    rate does not evolve on the tree.

    Tree growth is controlled by one or more of the following arguments, of which
    at least one must be specified:

        - If ``ntax`` is given as a keyword argument, tree is grown until the number of
          tips == ntax.
        - If ``taxon_namespace`` is given as a keyword argument, tree is grown until the
          number of tips == len(taxon_namespace), and the taxa are assigned randomly to the
          tips.
        - If 'max_time' is given as a keyword argument, tree is grown for
          a maximum of ``max_time``.
        - If ``gsa_ntax`` is given then the tree will be simulated up to this number of
          tips (or 0 tips), then a tree will be randomly selected from the
          intervals which corresond to times at which the tree had exactly ``ntax``
          leaves (or len(taxon_namespace) tips). This allows for simulations according to
          the "General Sampling Approach" of [citeHartmannWS2010]_


    If more than one of the above is given, then tree growth will terminate when
    *any* of the termination conditions (i.e., number of tips == ``ntax``, or number
    of tips == len(taxon_namespace) or maximum time = ``max_time``) are met.

    Also accepts a Tree object (with valid branch lengths) as an argument passed
    using the keyword ``tree``: if given, then this tree will be used; otherwise
    a new one will be created.

    If ``assign_taxa`` is False, then taxa will *not* be assigned to the tips;
    otherwise (default), taxa will be assigned. If ``taxon_namespace`` is given
    (``tree.taxon_namespace``, if ``tree`` is given), and the final number of tips on the
    tree after the termination condition is reached is less then the number of
    taxa in ``taxon_namespace`` (as will be the case, for example, when
    ``ntax`` < len(``taxon_namespace``)), then a random subset of taxa in ``taxon_namespace`` will
    be assigned to the tips of tree. If the number of tips is more than the number
    of taxa in the ``taxon_namespace``, new Taxon objects will be created and added
    to the ``taxon_namespace`` if the keyword argument ``create_required_taxa`` is not given as
    False.

    Under some conditions, it is possible for all lineages on a tree to go extinct.
    In this case, if the keyword argument ``repeat_until_success`` is `True` (the
    default), then a new branching process is initiated.
    If `False` (default), then a TreeSimTotalExtinctionException is raised.

    A Random() object or equivalent can be passed using the ``rng`` keyword;
    otherwise GLOBAL_RNG is used.

    .. [citeHartmannWS2010] Hartmann, Wong, and Stadler "Sampling Trees from Evolutionary Models" Systematic Biology. 2010. 59(4). 465-476

    """
    target_num_taxa = kwargs.get('ntax')
    max_time = kwargs.get('max_time')
    taxon_namespace = kwargs.get('taxon_namespace')
    if (target_num_taxa is None) and (taxon_namespace is not None):
        target_num_taxa = len(taxon_namespace)
    elif taxon_namespace is None:
        taxon_namespace = dendropy.TaxonNamespace()
    gsa_ntax = kwargs.get('gsa_ntax')
    terminate_at_full_tree = False
    if target_num_taxa is None:
        if gsa_ntax is not None:
            raise ValueError("When 'gsa_ntax' is used, either 'ntax' or 'taxon_namespace' must be used")
        if max_time is None:
            raise ValueError("At least one of the following must be specified: 'ntax', 'taxon_namespace', or 'max_time'")
    else:
        if gsa_ntax is None:
            terminate_at_full_tree = True
            gsa_ntax = 1 + target_num_taxa
        elif gsa_ntax < target_num_taxa:
            raise ValueError("gsa_ntax must be greater than target_num_taxa")
    repeat_until_success = kwargs.get('repeat_until_success', True)
    rng = kwargs.get('rng', GLOBAL_RNG)

    # initialize tree
    if "tree" in kwargs:
        tree = kwargs['tree']
        if "taxon_namespace" in kwargs and kwargs['taxon_namespace'] is not tree.taxon_namespace:
            raise ValueError("Cannot specify both ``tree`` and ``taxon_namespace``")
    else:
        tree = dendropy.Tree(taxon_namespace=taxon_namespace)
        tree.is_rooted = True
        tree.seed_node.edge.length = 0.0
        tree.seed_node.birth_rate = birth_rate
        tree.seed_node.death_rate = death_rate

    # grow tree
    leaf_nodes = tree.leaf_nodes()
    #_LOG.debug("Will generate a tree with no more than %s leaves to get a tree of %s leaves" % (str(gsa_ntax), str(target_num_taxa)))
    curr_num_leaves = len(leaf_nodes)
    total_time = 0
    # for the GSA simulations targetted_time_slices is a list of tuple
    #   the first element in the tuple is the duration of the amount
    #   that the simulation spent at the (targetted) number of taxa
    #   and a list of edge information. The list of edge information includes
    #   a list of terminal edges in the tree and the length for that edge
    #   that marks the beginning of the time slice that corresponds to the
    #   targetted number of taxa.

    targetted_time_slices = []
    extinct_tips = []
    while True:
        if gsa_ntax is None:
            assert (max_time is not None)
            if total_time >= max_time:
                break
        elif curr_num_leaves >= gsa_ntax:
            break

        # get vector of birth/death probabilities, and
        # associate with nodes/events
        event_rates = []
        event_nodes = []
        for nd in leaf_nodes:
            if not hasattr(nd, 'birth_rate'):
                nd.birth_rate = birth_rate
            if not hasattr(nd, 'death_rate'):
                nd.death_rate = death_rate
            event_rates.append(nd.birth_rate)
            event_nodes.append((nd, True)) # birth event = True
            event_rates.append(nd.death_rate)
            event_nodes.append((nd, False)) # birth event = False; i.e. death

        # get total probability of any birth/death
        rate_of_any_event = sum(event_rates)

        # waiting time based on above probability
        #_LOG.debug("rate_of_any_event = %f" % (rate_of_any_event))
        waiting_time = rng.expovariate(rate_of_any_event)
        #_LOG.debug("Drew waiting time of %f from hazard parameter of %f" % (waiting_time, rate_of_any_event))

        if (gsa_ntax is not None) and (curr_num_leaves == target_num_taxa):
            edge_and_start_length = []
            for nd in leaf_nodes:
                e = nd.edge
                edge_and_start_length.append((e, e.length))
            targetted_time_slices.append((waiting_time, edge_and_start_length))
            #_LOG.debug("Recording slice with %d edges" % len(edge_and_start_length))
            if terminate_at_full_tree:
                break

        # add waiting time to nodes
        for nd in leaf_nodes:
            try:
                nd.edge.length += waiting_time
            except TypeError:
                nd.edge.length = waiting_time
        #_LOG.debug("Next waiting_time = %f" % waiting_time)
        total_time += waiting_time

        # if event occurs within time constraints
        if max_time is None or total_time <= max_time:

            # normalize probability
            for i in range(len(event_rates)):
                event_rates[i] = event_rates[i]/rate_of_any_event

            # select node/event and process
            nd, birth_event = probability.weighted_choice(event_nodes, event_rates, rng=rng)
            leaf_nodes.remove(nd)
            curr_num_leaves -= 1
            if birth_event:
                #_LOG.debug("Speciation")
                c1 = nd.new_child()
                c2 = nd.new_child()
                c1.edge.length = 0
                c2.edge.length = 0
                c1.birth_rate = nd.birth_rate + rng.gauss(0, birth_rate_sd)
                c1.death_rate = nd.death_rate + rng.gauss(0, death_rate_sd)
                c2.birth_rate = nd.birth_rate + rng.gauss(0, birth_rate_sd)
                c2.death_rate = nd.death_rate + rng.gauss(0, death_rate_sd)
                leaf_nodes.append(c1)
                leaf_nodes.append(c2)
                curr_num_leaves += 2
            else:
                #_LOG.debug("Extinction")
                if curr_num_leaves > 0:
                    #_LOG.debug("Will delete " + str(id(nd)) + " with parent = " + str(id(nd.parent_node)))
                    extinct_tips.append(nd)
                else:
                    if (gsa_ntax is not None):
                        if (len(targetted_time_slices) > 0):
                            break
                    if not repeat_until_success:
                        raise TreeSimTotalExtinctionException()
                    # We are going to basically restart the simulation because the tree has gone extinct (without reaching the specified ntax)
                    leaf_nodes = [tree.seed_node]
                    curr_num_leaves = 1
                    for nd in tree.seed_node.child_nodes():
                        tree.prune_subtree(nd, suppress_unifurcations=False)
                    extinct_tips = []
                    total_time = 0
            assert(curr_num_leaves == len(leaf_nodes))
            #_LOG.debug("Current tree \n%s" % (tree.as_ascii_plot(plot_metric='length', show_internal_node_labels=True)))
    #tree._debug_tree_is_valid()
    #_LOG.debug("Terminated with %d leaves (%d, %d  according to len(leaf_nodes))" % (curr_num_leaves, len(leaf_nodes), len(tree.leaf_nodes())))
    if gsa_ntax is not None:
        total_duration_at_target_n_tax = 0.0
        for i in targetted_time_slices:
            total_duration_at_target_n_tax += i[0]
        r = rng.random()*total_duration_at_target_n_tax
        #_LOG.debug("Selected rng = %f out of (0, %f)" % (r, total_duration_at_target_n_tax))
        selected_slice = None
        for n, i in enumerate(targetted_time_slices):
            r -= i[0]
            if r < 0.0:
                selected_slice = i
        assert(selected_slice is not None)
        #_LOG.debug("Selected time slice index %d" % n)
        edges_at_slice = selected_slice[1]
        last_waiting_time = selected_slice[0]
        for e, prev_length in edges_at_slice:
            daughter_nd = e.head_node
            for nd in daughter_nd.child_nodes():
                tree.prune_subtree(nd, suppress_unifurcations=False)
                #_LOG.debug("After pruning %s:\n%s" % (str(id(nd)), tree.as_ascii_plot(plot_metric='length', show_internal_node_labels=True)))
                try:
                    extinct_tips.remove(nd)
                except:
                    pass
            try:
                extinct_tips.remove(daughter_nd)
            except:
                pass
            e.length = prev_length + last_waiting_time



#     tree._debug_tree_is_valid()
#     for nd in extinct_tips:
#         _LOG.debug("Will be deleting " + str(id(nd)))

    for nd in extinct_tips:
        bef = len(tree.leaf_nodes())
        while (nd.parent_node is not None) and (len(nd.parent_node.child_nodes()) == 1):
            nd = nd.parent_node
#         _LOG.debug("Deleting " + str(nd.__dict__) + '\n' + str(nd.edge.__dict__))
#         for n, pnd in enumerate(tree.postorder_node_iter()):
#             _LOG.debug("%d %s" % (n, repr(pnd)))
#        _LOG.debug("Before prune of %s:\n%s" % (str(id(nd)), tree.as_ascii_plot(plot_metric='length', show_internal_node_labels=True)))
        if nd.parent_node:
            tree.prune_subtree(nd, suppress_unifurcations=False)
#         _LOG.debug("Deleted " + str(nd.__dict__))
#         for n, pnd in enumerate(tree.postorder_node_iter()):
#             _LOG.debug("%d %s" % (n, repr(pnd)))
#         tree._debug_tree_is_valid()
    tree.suppress_unifurcations()
#    tree._debug_tree_is_valid()
#    _LOG.debug("After deg2suppression:\n%s" % (tree.as_ascii_plot(plot_metric='length', show_internal_node_labels=True)))

    if kwargs.get("assign_taxa", True):
        tree.randomly_assign_taxa(create_required_taxa=True, rng=rng)


    # return
    return tree


def discrete_birth_death_tree(birth_rate, death_rate, birth_rate_sd=0.0, death_rate_sd=0.0, **kwargs):
    """
    Returns a birth-death tree with birth rate specified by ``birth_rate``, and
    death rate specified by ``death_rate``, with edge lengths in discrete (integer)
    units.

    ``birth_rate_sd`` is the standard deviation of the normally-distributed mutation
    added to the birth rate as it is inherited by daughter nodes; if 0, birth
    rate does not evolve on the tree.

    ``death_rate_sd`` is the standard deviation of the normally-distributed mutation
    added to the death rate as it is inherited by daughter nodes; if 0, death
    rate does not evolve on the tree.

    Tree growth is controlled by one or more of the following arguments, of which
    at least one must be specified:

        - If ``ntax`` is given as a keyword argument, tree is grown until the number of
          tips == ntax.
        - If ``taxon_namespace`` is given as a keyword argument, tree is grown until the
          number of tips == len(taxon_namespace), and the taxa are assigned randomly to the
          tips.
        - If 'max_time' is given as a keyword argument, tree is grown for ``max_time``
          number of generations.

    If more than one of the above is given, then tree growth will terminate when
    *any* of the termination conditions (i.e., number of tips == ``ntax``, or number
    of tips == len(taxon_namespace) or number of generations = ``max_time``) are met.

    Also accepts a Tree object (with valid branch lengths) as an argument passed
    using the keyword ``tree``: if given, then this tree will be used; otherwise
    a new one will be created.

    If ``assign_taxa`` is False, then taxa will *not* be assigned to the tips;
    otherwise (default), taxa will be assigned. If ``taxon_namespace`` is given
    (``tree.taxon_namespace``, if ``tree`` is given), and the final number of tips on the
    tree after the termination condition is reached is less then the number of
    taxa in ``taxon_namespace`` (as will be the case, for example, when
    ``ntax`` < len(``taxon_namespace``)), then a random subset of taxa in ``taxon_namespace`` will
    be assigned to the tips of tree. If the number of tips is more than the number
    of taxa in the ``taxon_namespace``, new Taxon objects will be created and added
    to the ``taxon_namespace`` if the keyword argument ``create_required_taxa`` is not given as
    False.

    Under some conditions, it is possible for all lineages on a tree to go extinct.
    In this case, if the keyword argument ``repeat_until_success`` is `True`, then a new
    branching process is initiated.
    If `False` (default), then a TreeSimTotalExtinctionException is raised.

    A Random() object or equivalent can be passed using the ``rng`` keyword;
    otherwise GLOBAL_RNG is used.
    """
    if 'ntax' not in kwargs \
        and 'taxon_namespace' not in kwargs \
        and 'max_time' not in kwargs:
            raise ValueError("At least one of the following must be specified: 'ntax', 'taxon_namespace', or 'max_time'")
    target_num_taxa = None
    taxon_namespace = None
    target_num_gens = kwargs.get('max_time', None)
    if 'taxon_namespace' in kwargs:
        taxon_namespace = kwargs.get('taxon_namespace')
        target_num_taxa = kwargs.get('ntax', len(taxon_namespace))
    elif 'ntax' in kwargs:
        target_num_taxa = kwargs['ntax']
    if taxon_namespace is None:
        taxon_namespace = dendropy.TaxonNamespace()
    repeat_until_success = kwargs.get('repeat_until_success', False)
    rng = kwargs.get('rng', GLOBAL_RNG)

    # grow tree
    if "tree" in kwargs:
        tree = kwargs['tree']
        if "taxon_namespace" in kwargs and kwargs['taxon_namespace'] is not tree.taxon_namespace:
            raise ValueError("Cannot specify both ``tree`` and ``taxon_namespace``")
    else:
        tree = dendropy.Tree(taxon_namespace=taxon_namespace)
        tree.is_rooted = True
        tree.seed_node.edge.length = 0
        tree.seed_node.birth_rate = birth_rate
        tree.seed_node.death_rate = death_rate
    leaf_nodes = tree.leaf_nodes()
    num_gens = 0
    while (target_num_taxa is None or len(leaf_nodes) < target_num_taxa) \
            and (target_num_gens is None or num_gens < target_num_gens):
        for nd in leaf_nodes:
            if not hasattr(nd, 'birth_rate'):
                nd.birth_rate = birth_rate
            if not hasattr(nd, 'death_rate'):
                nd.death_rate = death_rate
            try:
                nd.edge.length += 1
            except TypeError:
                nd.edge.length = 1
            u = rng.uniform(0, 1)
            if u < nd.birth_rate:
                c1 = nd.new_child()
                c2 = nd.new_child()
                c1.edge.length = 0
                c2.edge.length = 0
                c1.birth_rate = nd.birth_rate + rng.gauss(0, birth_rate_sd)
                c1.death_rate = nd.death_rate + rng.gauss(0, death_rate_sd)
                c2.birth_rate = nd.birth_rate + rng.gauss(0, birth_rate_sd)
                c2.death_rate = nd.death_rate + rng.gauss(0, death_rate_sd)
            elif u > nd.birth_rate and u < (nd.birth_rate + nd.death_rate):
                if nd is not tree.seed_node:
                    tree.prune_subtree(nd)
                elif not repeat_until_success:
                    # all lineages are extinct: raise exception
                    raise TreeSimTotalExtinctionException()
                else:
                    # all lineages are extinct: repeat
                    num_gens = 0

        num_gens += 1
        leaf_nodes = tree.leaf_nodes()

    # If termination condition specified by ntax or taxon_namespace, then the last
    # split will have a daughter edges of length == 0;
    # so we continue growing the edges until the next birth/death event *or*
    # the max number of generations condition is given and met
    gens_to_add = 0
    while (target_num_gens is None or num_gens < target_num_gens):
        u = rng.uniform(0, 1)
        if u < (birth_rate + death_rate):
            break
        gens_to_add += 1
    for nd in tree.leaf_nodes():
        nd.edge.length += gens_to_add

    if kwargs.get("assign_taxa", True):
        tree.randomly_assign_taxa(create_required_taxa=True, rng=rng)

    # return
    return tree

def uniform_pure_birth_tree(taxon_namespace, birth_rate=1.0, rng=None):
    "Generates a uniform-rate pure-birth process tree. "
    if rng is None:
        rng = GLOBAL_RNG # use the global rng by default
    tree = dendropy.Tree(taxon_namespace=taxon_namespace)
    tree.seed_node.edge.length = 0.0
    leaf_nodes = tree.leaf_nodes()
    while len(leaf_nodes) < len(taxon_namespace):
        waiting_time = rng.expovariate(len(leaf_nodes)/birth_rate)
        for nd in leaf_nodes:
            nd.edge.length += waiting_time
        parent_node = rng.choice(leaf_nodes)
        c1 = parent_node.new_child()
        c2 = parent_node.new_child()
        c1.edge.length = 0.0
        c2.edge.length = 0.0
        leaf_nodes = tree.leaf_nodes()
    leaf_nodes = tree.leaf_nodes()
    waiting_time = rng.expovariate(len(leaf_nodes)/birth_rate)
    for nd in leaf_nodes:
        nd.edge.length += waiting_time
    for idx, leaf in enumerate(leaf_nodes):
        leaf.taxon = taxon_namespace[idx]
    tree.is_rooted = True
    return tree

def fit_pure_birth_model(**kwargs):
    """
    Calculates the maximum-likelihood estimate of the birth rate of a set of
    *internal* node ages under a Yule (pure-birth) model.

    Requires either a |Tree| object or an interable of *internal* node
    ages to be passed in via keyword arguments ``tree`` or ``internal_node_ages``,
    respectively. The former is more convenient when doing one-off
    calculations, while the latter is more efficient if the list of internal
    node ages needs to be used in other places and you already have it
    calculated and want to avoid re-calculating it here.

    Parameters
    ----------
    \*\*kwargs : keyword arguments, mandatory

        Exactly *one* of the following *must* be specified:

            tree : a |Tree| object.
                A |Tree| object. The tree needs to be ultrametric for the
                internal node ages (time from each internal node to the tips)
                to make sense. The precision by which the ultrametricity is
                checked can be specified using the ``ultrametricity_precision`` keyword
                argument (see below). If ``tree`` is given, then
                ``internal_node_ages`` cannot be given, and vice versa. If ``tree``
                is not given, then ``internal_node_ages`` must be given.
            internal_node_ages : iterable (of numerical values)
                Iterable of node ages of the internal nodes of a tree, i.e., the
                list of sum of the edge lengths between each internal node and
                the tips of the tree. If ``internal_node_ages`` is given, then
                ``tree`` cannot be given, and vice versa. If ``internal_node_ages``
                is not given, then ``tree`` must be given.

        While the following is optional, and is only used if internal node ages
        need to be calculated (i.e., 'tree' is passed in).

            ultrametricity_precision : float
                When calculating the node ages, an error will be raised if the tree in
                o ultrametric. This error may be due to floating-point or numerical
                imprecision. You can set the precision of the ultrametricity validation
                by setting the ``ultrametricity_precision`` parameter. E.g., use
                ``ultrametricity_precision=0.01`` for a more relaxed precision,
                down to 2 decimal places. Use ``ultrametricity_precision=False``
                to disable checking of ultrametricity precision.

            ignore_likelihood_calculation_failure: bool (default: False)
                In some cases (typically, abnormal trees, e.g., 1-tip), the
                likelihood estimation will fail. In this case a ValueError will
                be raised. If ``ignore_likelihood_calculation_failure`` is
                `True`, then the function call will still succeed, with the
                likelihood set to -``inf``.

    Returns
    -------
    m : dictionary

    A dictionary with keys being parameter names and values being
    estimates:

        "birth_rate"
            The birth rate.
        "log_likelihood"
            The log-likelihood of the model and given birth rate.

    Examples
    --------

    Given trees such as::

        import dendropy
        from dendropy.model import birthdeath
        trees = dendropy.TreeList.get_from_path(
                "pythonidae.nex", "nexus")

    Birth rates can be estimated by passing in trees directly::

        for idx, tree in enumerate(trees):
            m = birthdeath.fit_pure_birth_model(tree=tree)
            print("Tree {}: birth rate = {} (logL = {})".format(
                idx+1, m["birth_rate"], m["log_likelihood"]))

    Or by pre-calculating and passing in a list of node ages::

        for idx, tree in enumerate(trees):
            m = birthdeath.fit_pure_birth_model(
                    internal_node_ages=tree.internal_node_ages())
            print("Tree {}: birth rate = {} (logL = {})".format(
                idx+1, m["birth_rate"], m["log_likelihood"]))


    Notes
    -----
    Adapted from the laser package for R:

        -   Dan Rabosky and Klaus Schliep (2013). laser: Likelihood Analysis of
            Speciation/Extinction Rates from Phylogenies. R package version
            2.4-1. http://CRAN.R-project.org/package=laser

    See also:

        -   Nee, S.  2001.  Inferring speciation rates from phylogenies.
            Evolution 55:661-668.
        -   Yule, G. U. 1924. A mathematical theory of evolution based on the
            conclusions of Dr.  J. C. Willis. Phil. Trans. R. Soc. Lond. B
            213:21-87.

    """
    tree = kwargs.get("tree", None)
    if tree is not None:
        internal_node_ages = tree.internal_node_ages(ultrametricity_precision=kwargs.get("ultrametricity_precision", 0.0000001))
    else:
        try:
            internal_node_ages = kwargs["internal_node_ages"]
        except KeyError:
            raise TypeError("Need to specify 'tree' or 'internal_node_ages'")
    x = sorted(internal_node_ages, reverse=True)
    st1 = x[0]
    st2 = 0
    nvec = range(2, len(x)+2)
    nv = [i for i in x if (i < st1) and (i >= st2)]
    lo = max(nvec[idx] for idx, i in enumerate(x) if i >= st1)
    up = max(nvec[idx] for idx, i in enumerate(x) if i >= st2)
    if st1 <= x[0]:
        nv.insert(0, st1)
        nv = [i - st2 for i in nv]
    else:
        nv = [i - st2 for i in nv]
    t1 = (up-lo)
    t2 = (lo*nv[0])
    t3 = sum( nv[1:(up-lo+1)] )
    smax = t1/(t2 + t3)

    try:
        s1 = sum(map(math.log, range(lo,up)))
        s2 = (up-lo) * math.log(smax)
        s3 = lo - up
        lh = s1 + s2 + s3
    except ValueError:
        if kwargs.get("ignore_likelihood_calculation_failure", False):
            raise ValueError("Likelihood estimation failure")
        else:
            lh = float("-inf")

    result = {
        "birth_rate" : smax,
        "log_likelihood" : lh,
    }
    return result

def fit_pure_birth_model_to_tree(tree, ultrametricity_precision=constants.DEFAULT_ULTRAMETRICITY_PRECISION):
    """
    Calculates the maximum-likelihood estimate of the birth rate a tree under a
    Yule (pure-birth) model.

    Parameters
    ----------
    tree : |Tree| object
        A tree to be fitted.

    Returns
    -------
    m : dictionary

    A dictionary with keys being parameter names and values being
    estimates:

        -   "birth_rate"
            The birth rate.
        -   "log_likelihood"
            The log-likelihood of the model and given birth rate.

    Examples
    --------

    ::

        import dendropy
        from dendropy.model import birthdeath
        trees = dendropy.TreeList.get_from_path(
                "pythonidae.nex", "nexus")
        for idx, tree in enumerate(trees):
            m = birthdeath.fit_pure_birth_model_to_tree(tree)
            print("Tree {}: birth rate = {} (logL = {})".format(
                idx+1, m["birth_rate"], m["log_likelihood"]))

    """
    return fit_pure_birth_model(tree=tree, ultrametricity_precision=ultrametricity_precision)



class ProtractedSpeciationModel(object):

    class ProtractedSpeciationModelLineage(object):

        def __init__(self,
                index,
                parent_lineage,
                speciation_initiation_time,
                is_full_species):
            self.index = index
            self.is_full_species = is_full_species
            self.parent_lineage = parent_lineage
            self.speciation_initiation_time = speciation_initiation_time
            self.speciation_completion_time = None
            self.extinction_time = None
            self.psm_tree_node_history = []

        def _get_node(self):
            return self.psm_tree_node_history[-1]
        def _set_node(self, node):
            self.psm_tree_node_history.append(node)
        node = property(_get_node, _set_node)

    def __init__(self,
            full_species_birth_rate,
            full_species_extinction_rate,
            incipient_species_birth_rate,
            incipient_species_conversion_rate,
            incipient_species_extinction_rate,
            rng=None,
            ):
        self.full_species_birth_rate = full_species_birth_rate
        self.full_species_extinction_rate = full_species_extinction_rate
        self.incipient_species_birth_rate = incipient_species_birth_rate
        self.incipient_species_conversion_rate = incipient_species_conversion_rate
        self.incipient_species_extinction_rate = incipient_species_extinction_rate
        if rng is None:
            self.rng = GLOBAL_RNG
        else:
            self.rng = rng
        self.tree_factory = dendropy.Tree
        self.node_factory = dendropy.Node
        self.reset()

    def reset(self):
        self.current_time = 0.0
        self.current_lineage_index = 0
        self.current_node_index = 0
        self.current_full_species_lineages = []
        self.current_incipient_species_lineages = []
        self._all_lineages = []

    def generate_sample(self, **kwargs):
        """

        Samples from the Protracted Speciation Model process, returning a tuple of trees.

        -   The unpruned PSM tree: this tree has all nodes/lineages, i.e. both
            full species as well as incipient species. Nodes on the tree which
            represent full/good/true speciation events will have the attribute
            ``is_full_speciation_event`` set to `True`, while this attribute will
            be set to `False` otherwise.

        -   The pruned tree: the tree only has full species.

        Parameters
        ----------

        max_time : float
            Length of time for which to run process.
        is_initial_species_incipient : bool
            Whether the first lineage that initialies the process is an
            incipient or full species. Defaults to `False`: first species on
            the tree is a full species.
        is_retry_on_total_extinction : bool
            If ``False``, then a TreeSimTotalExtinctionException will be raised
            if all lineages go extinct before the termination conditions are
            met. Defaults to ``True``: if all lineages go extinct before the
            termination conditions are met, then the simulation is rerun, up to
            a maximum of ``max_retries``.
        max_retries : int
            Maximum number of runs to execute in the event of
            prematurely-terminated simulations due to all lineages going
            extinct. Once this number or re-runs is exceed, then
            TreeSimTotalExtinctionException is raised. Defaults to 1000. Set to
            ``None`` to never quit trying.

        Returns
        -------
        protracted_speciation_tree : |Tree| instance
            A tree from the protracted speciation process, with all lineages
            (full species as well as incipient species).
        pruned_tree : |Tree| instance
            A tree from the protracted speciation process with only full species.

        """
        is_retry_on_total_extinction = kwargs.pop("is_retry_on_total_extinction", True)
        max_retries = kwargs.pop("max_retries", 1000)
        num_retries = 0
        psm_tree = None
        pruned_tree = None
        while True:
            try:
                psm_tree, pruned_tree = self._run_protracted_speciation_process(**kwargs)
                break
            except TreeSimTotalExtinctionException:
                if not is_retry_on_total_extinction:
                    raise
                num_retries += 1
                if max_retries is not None and num_retries > max_retries:
                    raise
        assert psm_tree is not None
        return psm_tree, pruned_tree

    def _run_protracted_speciation_process(self, **kwargs):
        self.reset()
        max_time = kwargs.get("max_time", None)
        taxon_namespace = kwargs.get("taxon_namespace", None)

        is_full_species = not kwargs.get("is_initial_species_incipient", False)
        if is_full_species:
            initial_lineage = self._new_lineage(parent_lineage=None, is_full_species=True)
        else:
            initial_lineage = self._new_lineage(parent_lineage=None, is_full_species=False)
        seed_node = self._new_node(lineage=initial_lineage)
        psm_tree = self.tree_factory( taxon_namespace=taxon_namespace, seed_node=seed_node)
        psm_tree.is_rooted = True

        while True:

            ## Draw time to next event
            event_rates = []
            num_full_species = len(self.current_full_species_lineages)
            num_incipient_species = len(self.current_incipient_species_lineages)

            # Event type 0
            event_rates.append(self.full_species_birth_rate * num_full_species)

            # Event type 1
            event_rates.append(self.full_species_extinction_rate * num_full_species)

            # Event type 2
            event_rates.append(self.incipient_species_birth_rate * num_incipient_species)

            # Event type 3
            event_rates.append(self.incipient_species_conversion_rate * num_incipient_species)

            # Event type 4
            event_rates.append(self.incipient_species_extinction_rate * num_incipient_species)

            # All events
            rate_of_any_event = sum(event_rates)

            # Waiting time
            waiting_time = self.rng.expovariate(rate_of_any_event)
            if max_time and (self.current_time + waiting_time) > max_time:
                t = max_time - self.current_time
                for lineage in itertools.chain(self.current_full_species_lineages, self.current_incipient_species_lineages):
                    lineage.node.edge.length += t
                self.current_time = max_time
                break
            self.current_time += waiting_time
            for lineage in itertools.chain(self.current_full_species_lineages, self.current_incipient_species_lineages):
                lineage.node.edge.length += waiting_time

            # Select event
            event_type_idx = probability.weighted_index_choice(weights=event_rates, rng=self.rng)
            assert (event_type_idx >= 0 and event_type_idx <= 4)
            # print("time {}: {}, selected = {}".format(self.current_time, event_rates, event_type_idx))

            if event_type_idx == 0:
                self._process_full_species_birth(psm_tree)
            elif event_type_idx == 1:
                self._process_full_species_extinction(psm_tree)
            elif event_type_idx == 2:
                self._process_incipient_species_birth(psm_tree)
            elif event_type_idx == 3:
                self._process_incipient_species_conversion(psm_tree)
            elif event_type_idx == 4:
                self._process_incipient_species_extinction(psm_tree)
            else:
                raise Exception("Unexpected event type index: {}".format(event_type_idx))

            if len(self.current_full_species_lineages) + len(self.current_incipient_species_lineages) == 0:
                raise TreeSimTotalExtinctionException()

        pruned_tree = self._assemble_pruned_tree(taxon_namespace=taxon_namespace)
        psm_tree.calc_node_ages()
        for pruned_tree_nd in pruned_tree:
            if pruned_tree_nd.is_leaf():
                continue
            # sys.stderr.write("{}: {}\n".format(pruned_tree_nd.age, list(nd.age for nd in pruned_tree_nd.protracted_speciation_model_lineage.psm_tree_node_history)))
            psm_tree_node = pruned_tree_nd.protracted_speciation_model_lineage.psm_tree_node_history[0]
            for nd in pruned_tree_nd.protracted_speciation_model_lineage.psm_tree_node_history:
                if nd.age is not None and nd.age > psm_tree_node.age:
                    psm_tree_node = nd
                # nd.is_full_speciation_event = True
            psm_tree_node.is_full_speciation_event = True
            pruned_tree_nd.protracted_speciation_model_tree_node = psm_tree_node

        return psm_tree, pruned_tree

    def _process_full_species_birth(self, tree):
        parent_lineage = self.rng.choice(self.current_full_species_lineages)
        parent_node = parent_lineage.node
        new_lineage = self._new_lineage(parent_lineage=parent_lineage, is_full_species=False)
        c1 = self._new_node(lineage=parent_lineage)
        c2 = self._new_node(lineage=new_lineage)
        parent_node.add_child(c1)
        parent_node.add_child(c2)

    def _process_full_species_extinction(self, tree):
        sp = self.rng.choice(self.current_full_species_lineages)
        sp.extinction_time = self.current_time
        self.current_full_species_lineages.remove(sp)
        self._make_lineage_extinct_on_phylogeny(tree, sp.node)

    def _process_incipient_species_birth(self, tree):
        parent_lineage = self.rng.choice(self.current_incipient_species_lineages)
        parent_node = parent_lineage.node
        new_lineage = self._new_lineage(parent_lineage=parent_lineage, is_full_species=False)
        c1 = self._new_node(lineage=parent_lineage)
        c2 = self._new_node(lineage=new_lineage)
        parent_node.add_child(c1)
        parent_node.add_child(c2)

    def _process_incipient_species_conversion(self, tree):
        lineage = self.rng.choice(self.current_incipient_species_lineages)
        self.current_incipient_species_lineages.remove(lineage)
        self.current_full_species_lineages.append(lineage)
        lineage.is_full_species = True
        lineage.speciation_completion_time = self.current_time

    def _process_incipient_species_extinction(self, tree):
        sp = self.rng.choice(self.current_incipient_species_lineages)
        sp.extinction_time = self.current_time
        self.current_incipient_species_lineages.remove(sp)
        self._make_lineage_extinct_on_phylogeny(tree, sp.node)

    def _make_lineage_extinct_on_phylogeny(self, tree, sp):
        if len(self.current_full_species_lineages) == 0 and len(self.current_incipient_species_lineages) == 0:
            raise TreeSimTotalExtinctionException()
        tree.prune_subtree(sp)

    def _new_lineage(self, parent_lineage, is_full_species):
        self.current_lineage_index += 1
        lineage_index = self.current_lineage_index
        speciation_initiation_time = self.current_time
        new_lineage = ProtractedSpeciationModel.ProtractedSpeciationModelLineage(
                index=lineage_index,
                parent_lineage=parent_lineage,
                speciation_initiation_time=speciation_initiation_time,
                is_full_species=is_full_species)
        self._all_lineages.append(new_lineage)
        if is_full_species:
            self.current_full_species_lineages.append(new_lineage)
        else:
            self.current_incipient_species_lineages.append(new_lineage)
        return new_lineage

    def _new_node(self,
            lineage,
            ):
        node = self.node_factory()
        node.edge.length = 0.0
        node.protracted_speciation_model_lineage = lineage
        node.is_full_speciation_event = False
        node.annotations.add_bound_attribute("is_full_speciation_event")
        self.current_node_index += 1
        node.label = "L{}.n{}".format(lineage.index, self.current_node_index)
        lineage.node = node
        return node

    def _assemble_pruned_tree(self, taxon_namespace=None):
        lineage_set = set(self.current_incipient_species_lineages + self.current_full_species_lineages)
        sorted_lineages = sorted(lineage_set,
                key = lambda x: -x.speciation_initiation_time)
        # sys.stderr.write("\n--- full ---\n")
        # self._debug_dump_lineages(self._all_lineages)
        # sys.stderr.write("\n\n--- operational ---\n")
        # self._debug_dump_lineages(sorted_lineages)
        branching_points = {}
        while sorted_lineages:
            lineage = sorted_lineages.pop(0)
            lineage_set.remove(lineage)
            parent_lineage = lineage.parent_lineage
            if parent_lineage is None:
                break
            if lineage.is_full_species:
                # sys.stderr.write("\n")
                try:
                    full_species_tree_node = branching_points[lineage]
                    # sys.stderr.write("Lineage node already in dictionary, with child lineages: {}\n".format((ch.label for ch in full_species_tree_node.child_node_iter())))
                except KeyError:
                    # sys.stderr.write("Creating new lineage node: {}\n".format(lineage.index))
                    full_species_tree_node = dendropy.Node()
                    full_species_tree_node.label = "L{}".format(lineage.index)
                    full_species_tree_node.protracted_speciation_model_lineage = lineage
                    # full_species_tree_node.age = 0 # if creating new, then it is not a parent
                    branching_points[lineage] = full_species_tree_node
                if lineage.is_full_species:
                    parent_lineage.is_full_species = True
                # sys.stderr.write("\n")
                # sys.stderr.write("Lineage: {}\n".format(lineage.index))
                # lineage_set.add(parent_lineage)
                # sorted_lineages = sorted(lineage_set,
                #         key = lambda x: -x.speciation_initiation_time)
                try:
                    full_species_tree_parent_node = branching_points[parent_lineage]
                    # sys.stderr.write("{}: Parent lineage node {} already in dictionary, with child lineages: {}\n".format(lineage.index, parent_lineage.index, (ch.label for ch in full_species_tree_node.child_node_iter())))
                except KeyError:
                    # sys.stderr.write("{}: Creating new parent lineage node: {}\n".format(lineage.index, parent_lineage.index))
                    full_species_tree_parent_node = dendropy.Node()
                    full_species_tree_parent_node.label = "L{}".format(parent_lineage.index)
                    full_species_tree_parent_node.protracted_speciation_model_lineage = parent_lineage
                    # note that the age is the speciation initiation time of the *daughter*
                    # full_species_tree_parent_node.age = self.current_time - lineage.speciation_initiation_time
                    branching_points[parent_lineage] = full_species_tree_parent_node
                full_species_tree_parent_node.add_child(full_species_tree_node)
                if parent_lineage not in lineage_set:
                    lineage_set.add(parent_lineage)
                    sorted_lineages = sorted(lineage_set,
                            key = lambda x: -x.speciation_initiation_time)
        seed_node = None
        for nd in branching_points.values():
            if nd.parent_node is None:
                seed_node = nd
                break
        assert seed_node is not None
        pruned_tree = dendropy.Tree(taxon_namespace=taxon_namespace, seed_node=seed_node)
        pruned_tree.is_rooted = True
        # pruned_tree.suppress_unifurcations()
        # pruned_tree.set_edge_lengths_from_node_ages()

        for nd in pruned_tree.postorder_node_iter():
            # if nd.is_leaf():
            #     nd.edge.length = self.current_time - nd.protracted_speciation_model_lineage.speciation_initiation_time
            # else:
            #     nd.edge.length = nd._child_nodes[1].protracted_speciation_model_lineage.speciation_initiation_time - nd.protracted_speciation_model_lineage.speciation_initiation_time
            if nd.is_leaf():
                nd.age = 0
            else:
                nd.age = self.current_time - min(ch.protracted_speciation_model_lineage.speciation_initiation_time for ch in nd.child_node_iter())
        pruned_tree.set_edge_lengths_from_node_ages()
        pruned_tree.suppress_unifurcations()

        # for nd in pruned_tree.postorder_node_iter():
        #     if nd.is_leaf():
        #         nd.age = 0
        #     else:
        #         ages = []
        #         for ch in nd.child_node_iter():
        #             age = ch.protracted_speciation_model_lineage.speciation_initiation_time - ch.age
        #             ages.append(age)
        #             nd.age = age
        # for nd in pruned_tree.preorder_node_iter():
        #     if len(nd._child_nodes) == 1:
        #         ch = nd.new_child()
        #         ch.label = "dummy{}".format(id(ch))
        #         ch.age = 0
        # for nd in pruned_tree.preorder_node_iter():
        #     if nd.parent_node is None:
        #         nd.edge.length = nd.protracted_speciation_model_lineage.speciation_initiation_time
        #     else:
        #         nd.edge.length = nd.protracted_speciation_model_lineage.speciation_initiation_time - nd.parent_node.protracted_speciation_model_lineage.speciation_initiation_time

        return pruned_tree

    def _debug_dump_lineages(self, lineages):
        sorted_lineages = sorted(lineages,
                key = lambda x: -x.speciation_initiation_time)
        for k in sorted_lineages:
            if k.parent_lineage is None:
                pi = "NA"
                pt = "NA"
            else:
                pi = k.parent_lineage.index
                pt = k.parent_lineage.is_full_species
            # sys.stderr.write("{:10.5f} : {:4} ({}) => {} ({})\n".format(
            #         k.speciation_initiation_time,
            #         k.index,
            #         k.is_full_species,
            #         pi,
            #         pt))
        # sys.stderr.write("\n")
