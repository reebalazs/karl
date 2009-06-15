# Copyright (C) 2008-2009 Open Society Institute
#               Thomas Moroz: tmoroz@sorosny.org
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License Version 2 as published
# by the Free Software Foundation.  You may not use, modify or distribute
# this program under any other version of the GNU General Public License.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import re
from urllib import quote

from webob.exc import HTTPFound
from formencode import Invalid

from zope.component import getMultiAdapter
from zope.component import getAdapter

from repoze.bfg.security import authenticated_userid
from repoze.bfg.security import has_permission
from repoze.bfg.security import effective_principals
from repoze.bfg.traversal import model_path

from repoze.lemonade.content import create_content

from repoze.bfg.url import model_url

from karl.views.api import TemplateAPI
from karl.views.interfaces import IToolAddables
from karl.views.utils import make_name
from karl.views.batch import get_catalog_batch_grid
from karl.views import baseforms
from karl.views.utils import convert_to_script
from karl.views.tags import set_tags

from karl.utils import find_users
from karl.utils import get_setting

from repoze.bfg.chameleon_zpt import render_template
from repoze.bfg.chameleon_zpt import render_template_to_response

from karl.models.interfaces import ICommunityInfo
from karl.models.interfaces import ILetterManager
from karl.models.interfaces import ICommunity

from karl.security.interfaces import ISecurityWorkflow

def show_communities_view(context, request):

    page_title = 'KARL Communities'
    actions = []

    if has_permission('create', context, request):
        actions.append(('Add Community', 'add_community.html'))
    api = TemplateAPI(context, request, page_title)

    # Grab the data for the two listings, main communities and portlet
    communities_path = model_path(context)

    query = dict(
        sort_index='title',
        interfaces=[ICommunity],
        path={'query': communities_path, 'depth': 1},
        allowed={'query': effective_principals(request), 'operator': 'or'},
        )

    titlestartswith = request.params.get('titlestartswith')
    if titlestartswith:
        query['titlestartswith'] = (titlestartswith, titlestartswith)

    batch_info = get_catalog_batch_grid(context, request, **query)

    communities = []
    for community in batch_info['entries']:
        adapted = getMultiAdapter((community, request), ICommunityInfo)
        communities.append(adapted)

    mgr = ILetterManager(context)
    letter_info = mgr.get_info(request)

    my_communities = get_my_communities(context, request)

    return render_template_to_response(
        'templates/communities.pt',
        api=api,
        actions=actions,
        communities=communities,
        my_communities=my_communities,
        batch_info=batch_info,
        letters=letter_info,
        )

def get_my_communities(communities_folder, request):
    # sorted by title
    principals = effective_principals(request)
    communities = {}

    for name, role in get_community_groups(principals):
        if name in communities:
            continue
        try:
            community = communities_folder[name]
        except KeyError:
            continue
        communities[name] = (community.title, community)

    communities = communities.values()
    communities.sort()
    communities = [ x[1] for x in communities ]
    my_communities = []
    for community in communities:
        adapted = getMultiAdapter((community, request), ICommunityInfo)
        my_communities.append(adapted)
    return my_communities


from formencode import validators
class AddCommunityForm(baseforms.BaseForm):
    title = baseforms.title
    description = baseforms.description
    text = validators.UnicodeString(strip=True)
    sharing = baseforms.sharing
    tags = baseforms.tags

def add_community_view(context, request):

    system_name = get_setting(context, 'system_name')
    form = AddCommunityForm(request.POST, submit='form.submitted', 
                            cancel='form.cancel')

    if form.cancel in form.formdata:
        return HTTPFound(location=model_url(context, request))

    available_tools = getMultiAdapter((context, request), IToolAddables)()

    if form.submit in form.formdata:
        try:
            state = baseforms.AppState(tags_list=request.POST.getall('tags'))

            converted = form.to_python(form.fieldvalues, state)
            form.is_valid = True

            # Now add the community
            try:
                name = make_name(context, converted['title'])
            except ValueError, why:
                location = model_url(context, request, request.view_name)
                msg = why[0]
                location = location + "?status_message=" + quote(msg)
                return HTTPFound(location=location)

            userid = authenticated_userid(request)

            community = create_content(ICommunity,
                                       converted['title'],
                                       converted['description'],
                                       converted['text'],
                                       userid,
                                       )

            # required to use moderators_group_name and
            # members_group_name
            community.__name__ = name 

            for toolinfo in available_tools:
                if toolinfo['name'] in request.POST.keys():
                    toolinfo['component'].add(community, request)

            # By default the "default tool" is None (indicating 'overview')
            community.default_tool = None

            users = find_users(context)
            moderators_group_name = community.moderators_group_name
            members_group_name = community.members_group_name

            for group_name in moderators_group_name, members_group_name:
                users.add_group(userid, group_name)

            context[name] = community

            acl_adapter = getAdapter(community, ISecurityWorkflow)
            acl_adapter.setInitialState(**converted)

            # Save the tags on it.
            set_tags(community, request, converted['tags'])

            # Adding a community should take you to the Add Existing
            # User screen, so the moderator can include some users.
            location = model_url(community, request, 
                                 'members', 'add_existing.html')
            location = location + "?status_message=Community%20added"

            return HTTPFound(location=location)


        except Invalid, e:
            fielderrors = e.error_dict
            form.is_valid = False
            # Get the default list of tools into sequence of dicts AND
            # set checked state based on what the user typed in before
            # invalidation.
            tools = []
            for t in available_tools:
                state = request.POST.has_key(t['name'])
                tools.append(
                    {'name': t['name'], 'title': t['title'], 'state': state}
                    )

            # provide client data for rendering current tags in the tagbox.
            # We arrived here because the form is invalid.
            tagbox_records = [dict(tag=tag) for tag in
                              form.formdata.getall('tags')]

    else:
        fielderrors = {}

        # Get the default list of tools into a sequence of dicts

        tools = []
        for t in available_tools:
            tools.append(
                {'name': t['name'], 'title': t['title'], 'state': True}
                )

        # provide client data for rendering current tags in the tagbox.
        # Since this is a new entry, we start with no tags.
        tagbox_records = []

    # prepare client data
    client_json_data = dict(
        tags_field = dict(
            # There is no document right now, so we leave docid empty.
            # This will cause the count links become non-clickable. 
            records = tagbox_records,
            ),
    )

    # Render the form and shove some default values in
    page_title = 'Add Community'
    api = TemplateAPI(context, request, page_title)

    form_html = render_template(
        'templates/form_add_community.pt',
        post_url=request.url,
        formfields=api.formfields,
        fielderrors=fielderrors,
        tools=tools,
        api=api,
        )
    form.rendered_form = form.merge(form_html, form.fieldvalues)

    return render_template_to_response(
        'templates/add_community.pt',
        api=api,
        form=form,
        system_name=system_name,
        head_data=convert_to_script(client_json_data),
        )

community_name_regex = re.compile(
    r'^group.community:(?P<name>\S+):(?P<role>\S+)$'
    )

def get_community_groups(principals):
    groups = []
    for principal in principals:
        match = community_name_regex.match(principal)
        if match:
            name, role = match.groups()
            groups.append((name, role))
    return groups
