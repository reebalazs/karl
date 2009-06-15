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

import email.message
import urllib

from webob.exc import HTTPFound
from zope.component import getMultiAdapter
from zope.component import getUtility
from zope.component.event import objectEventNotify

from formencode import Invalid

from repoze.bfg.chameleon_zpt import render_template
from repoze.bfg.chameleon_zpt import render_template_to_response
from repoze.bfg.security import authenticated_userid
from repoze.bfg.security import effective_principals
from repoze.bfg.security import has_permission
from repoze.bfg.url import model_url
from repoze.lemonade.interfaces import IContent
from repoze.sendmail.interfaces import IMailDelivery

from karl.events import ObjectModifiedEvent
from karl.events import ObjectWillBeModifiedEvent

from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import ILetterManager
from karl.models.interfaces import IProfile
from karl.models.interfaces import IGridEntryInfo

from karl.views import baseforms
from karl.views.tags import get_tags_client_data

from karl.views.api import TemplateAPI

from karl.utils import find_communities
from karl.utils import find_tags
from karl.utils import find_users
from karl.utils import find_vocabularies
from karl.utils import get_setting
from karl.views.utils import convert_to_script
from karl.views.utils import handle_photo_upload
from karl.views.utils import CustomInvalid
from karl.views.batch import get_catalog_batch

from repoze.who.plugins.zodb.users import get_sha_password

def edit_profile_view(context, request):
    form = EditProfileForm(request.POST, submit="form.submitted",
                           cancel="form.cancel")

    if form.cancel in form.formdata:
        return HTTPFound(location=model_url(context, request))
            
    vocabularies = find_vocabularies(context)
    if form.submit in form.formdata:
        try:
            state = baseforms.AppState(vocabularies=vocabularies,
                                       context=context)
            
            converted = form.to_python(form.fieldvalues, state)
            form.is_valid = True

            objectEventNotify(ObjectWillBeModifiedEvent(context))
            
            # Handle simple fields
            for name in form.simple_field_names:
                setattr(context, name, converted.get(name))
            
            handle_photo_upload(context, converted)
            
            # Emit a modified event for recataloging
            objectEventNotify(ObjectModifiedEvent(context))
    
            path = model_url(context, request)
            msg = '?status_message=Profile%20edited'
            return HTTPFound(location=path+msg)

        except Invalid, e:
            fielderrors = e.error_dict
            fill_values = form.fieldvalues
            form.is_valid = False
    else:
        fielderrors = {}

        # pre-fill form with model values
        fill_values = form.from_python(context)
        
    page_title = 'Edit ' + context.title
    api = TemplateAPI(context, request, page_title)

    # Display portrait
    photo = context.get_photo()
    display_photo = {}
    if photo is not None:
        display_photo["url"] = model_url(photo, request)
        display_photo["may_delete"] = True
    else:
        display_photo["url"] = api.app_url + "/static/images/defaultUser.gif"
        display_photo["may_delete"] = False
        
    # Enable hiding of certain fields via CSS descendent selectors
    if api.user_is_staff:
        staff_role_classname = 'k3_staff_role'
    else:
        staff_role_classname = 'k3_nonstaff_role'

    staff_change_password_url = '%s?username=%s&email=%s&came_from=%s' % (
        get_setting(context, "staff_change_password_url"),
        urllib.quote_plus(context.__name__),
        urllib.quote_plus(context.email),
        urllib.quote_plus(api.here_url)
        )

    form_html = render_template(
        'templates/form_edit_profile.pt',
        post_url=request.url,
        formfields=api.formfields,
        fielderrors=fielderrors,
        api=api,
        vocabularies=vocabularies,
        photo=display_photo,
        staff_role_classname=staff_role_classname,
    )
 
    form.rendered_form = form.merge(form_html, fill_values)


    return render_template_to_response(
        'templates/edit_profile.pt',
        form=form,
        api=api,
        staff_change_password_url=staff_change_password_url,
        )        

class EditProfileForm(baseforms.BaseForm):
    simple_field_names = [
        "firstname",
        "lastname",
        "email",
        "phone",
        "extension",
        "department",
        "position",
        "organization",
        "location",
        "country",
        "website",
        "languages",
        "office",
        "room_no",
        "biography",
    ]
    
    firstname = baseforms.firstname
    lastname = baseforms.lastname
    email = baseforms.email
    phone = baseforms.phone
    extension = baseforms.extension
    department = baseforms.department
    position = baseforms.position
    organization = baseforms.organization
    location = baseforms.location
    country = baseforms.country
    website = baseforms.website
    languages = baseforms.languages
    photo = baseforms.photo
    photo_delete = baseforms.photo_delete
    biography = baseforms.biography
    
    def from_python(self, context, state=None):
        # Convert model object to dict and then call super method
        model_values = {}
        for name in self.simple_field_names:
            if hasattr(context, name):
                model_values[name] = getattr(context, name)
                
        model_values["photo"] = context.get("photo", None)
        model_values["photo_delete"] = False
        
        return super(EditProfileForm, self).from_python(model_values, state)
        
def get_profile_actions(profile, request):
    actions = []
    editable = authenticated_userid(request) == profile.__name__
    if editable:
        actions.append(('Edit', 'edit_profile.html'))
        actions.append(('Manage Communities', 'manage_communities.html'))
        actions.append(('Manage Tags', 'manage_tags.html'))
   
    return actions

def show_profile_view(context, request):
    """Show a profile with actions if the current user"""
    page_title = 'View Profile'
    api = TemplateAPI(context, request, page_title)
  
    # Create display values from model object
    profile = {}
    for name in [name for name in context.__dict__.keys() 
                 if not name.startswith("_")]:        
        profile_value = getattr(context, name)
        if profile_value is not None:
            # Don't produce u'None'
            profile[name] = unicode(profile_value)
        else:
            profile[name] = None

    if profile.has_key("languages"):
        profile["languages"] = context.languages
    
    if profile.has_key("department"):
        profile["department"] = context.department
        
    if profile.has_key("country"):
        # translate from country code to country name
        vocabularies = find_vocabularies(context)
        country_code = profile["country"]
        country = vocabularies["countries_dict"].get(country_code, u'')
        profile["country"] = country
        
    # Display portrait
    photo = context.get_photo()
    display_photo = {}
    if photo is not None:
        display_photo["url"] = model_url(photo, request)
    else:
        display_photo["url"] = api.static_url + "/images/defaultUser.gif"
    profile["photo"] = display_photo

    # provide client data for rendering current tags in the tagbox
    client_json_data = dict(
        tagbox = get_tags_client_data(context, request),
        )

    # Get communities this user is a member of, along with moderator info
    #
    communities = {}
    communities_folder = find_communities(context)
    user_info = find_users(context).get_by_id(context.__name__)
    if user_info is None:
        raise KeyError(context.__name__)

    for group in user_info["groups"]:
        if group.startswith("group.community:"):
            unused, community_name, role = group.split(":")
            if communities.has_key(community_name) and role != "moderators":
                continue

            community = communities_folder.get(community_name, None)
            if community is None:
                continue

            if has_permission('view', community, request):
                communities[community_name] = {
                    "title": community.title,
                    "moderator": role == "moderators",
                    "url": model_url(community, request),
                }

    communities = communities.values()
    communities.sort(key=lambda x:x["title"])

    tagger = find_tags(context)
    if tagger is None:
        tags = ()
    else:
        tags = []
        names = tagger.getTags(users=[context.__name__])
        for name, count in sorted(tagger.getFrequency(names,
                                                      user=context.__name__),
                                  key=lambda x: x[1],
                                  reverse=True,
                                 )[:10]:
            tags.append({'name': name, 'count': count})

    # List recently added content
    num, docids, resolver = ICatalogSearch(context)(
        sort_index='creation_date', reverse=True,
        interfaces=[IContent], limit=5, creator=context.__name__,
        allowed={'query': effective_principals(request), 'operator': 'or'},
        )
    recent_items = []
    for docid in docids:
        item = resolver(docid)
        if item is None:
            continue
        adapted = getMultiAdapter((item, request), IGridEntryInfo)
        recent_items.append(adapted)

    return render_template_to_response(
        'templates/profile.pt',
        api=api,
        profile=profile,
        actions=get_profile_actions(context, request),
        photo=photo,
        head_data=convert_to_script(client_json_data),
        communities=communities,
        tags=tags,
        recent_items=recent_items,
        )

def recent_content_view(context, request):
    batch = get_catalog_batch(context, request,
        sort_index='creation_date', reverse=True,
        interfaces=[IContent], creator=context.__name__,
        allowed={'query': effective_principals(request), 'operator': 'or'},
        )

    recent_items = []
    for item in batch['entries']:
        adapted = getMultiAdapter((item, request), IGridEntryInfo)
        recent_items.append(adapted)

    page_title = "Content Added Recently by %s" % context.title
    api = TemplateAPI(context, request, page_title)
    return render_template_to_response(
        'templates/profile_recent_content.pt',
        api=api,
        batch_info=batch,
        recent_items=recent_items,
        )

def may_leave(userid, community):
    # May not leave community if a moderator
    return userid not in community.moderator_names
    
    # Alternatively, may not leave community if *sole* moderator
    # may_leave = len(community.moderator_names) > 1 or \
    #           userid not in community.moderator_names
    
def manage_communities_view(context, request):
    assert IProfile.providedBy(context)
    
    page_title = 'Manage Communities'
    api = TemplateAPI(context, request, page_title)
    
    users = find_users(context)
    communities_folder = find_communities(context)
    userid = context.__name__
    
    # Handle cancel
    if request.params.get("form.cancel", False):
        return HTTPFound(location=model_url(context, request))
        
    # Handle form submission
    if request.params.get("form.submitted", False):
        for key in request.params:
            if key.startswith("leave_"):
                community_name = key[6:]
                community = communities_folder[community_name]
                
                # Not concerned about catching this exception, since checkbox
                # should not have been displayed in form unless user allowed
                # to leave.  Assert merely guards integrity of the system.
                assert may_leave(userid, community)
        
                if userid in community.moderator_names:
                    users.remove_group(userid, community.moderators_group_name)
                if userid in community.member_names:
                    users.remove_group(userid, community.members_group_name)
                
            elif key.startswith("alerts_pref_"):
                community_name = key[12:]
                preference = int(request.params.get(key))
                context.set_alerts_preference(community_name, preference)
                
        path = model_url(context, request)
        msg = '?status_message=Community+preferences+updated.'
        return HTTPFound(location=path+msg)

    communities = []
    for community in communities_folder.values():
        if (userid in community.member_names or 
            userid in community.moderator_names):
            alerts_pref = context.get_alerts_preference(community.__name__)
            display_community = {
                'name': community.__name__,
                'title': community.title,
                'alerts_pref': [
                    { "value": IProfile.ALERT_IMMEDIATELY,
                      "label": "Immediately",
                      "selected": alerts_pref == IProfile.ALERT_IMMEDIATELY,
                    },
                    { "value": IProfile.ALERT_DIGEST,
                      "label": "Digest",
                      "selected": alerts_pref == IProfile.ALERT_DIGEST,
                    },
                    { "value": IProfile.ALERT_NEVER,
                      "label": "Never",
                      "selected": alerts_pref == IProfile.ALERT_NEVER,
                    }],
                'may_leave': may_leave(userid, community),
            }
            communities.append(display_community)
            
    if len(communities) > 1:
        communities.sort(key=lambda x: x["title"])
        
    return render_template_to_response(
        'templates/manage_communities.pt',
        api=api,
        communities=communities,
        post_url=request.url,
        formfields=api.formfields,
    )
        
def show_profiles_view(context, request):

    page_title = 'KARL Profiles'
    api = TemplateAPI(context, request, page_title)

    # Grab the data for the two listings, main communities and portlet
    search = getMultiAdapter((context, request), ICatalogSearch)

    query = dict(sort_index='title', interfaces=[IProfile], limit=5)

    titlestartswith = request.params.get('titlestartswith')
    if titlestartswith:
        query['titlestartswith'] = (titlestartswith, titlestartswith)

    num, docids, resolver = search(**query)

    profiles = []
    for docid in docids:
        model = resolver(docid)
        if model is None:
            continue
        profiles.append(model)

    mgr = ILetterManager(context)
    letter_info = mgr.get_info(request)

    return render_template_to_response(
        'templates/profiles.pt',
        api=api,
        profiles=profiles,
        letters=letter_info,
        )

def change_password_view(context, request):
    form = ChangePasswordForm(request.POST, submit="form.submitted",
                              cancel="form.cancel")

    if form.cancel in form.formdata:
        return HTTPFound(location=model_url(context, request))

    if form.submit in form.formdata:
        try:
            min_pw_length = get_setting(context, 'min_pw_length')
            state = baseforms.AppState(min_pw_length=min_pw_length)
            converted = form.to_python(form.fieldvalues, state)
            form.is_valid = True

            users = find_users(context)
            userid = context.__name__
            user = users.get_by_id(userid)

            # check the old password
            # XXX: repoze.who.plugins.zodb.interfaces.IUsers
            # really should have a check_password(id, password)
            # method.  We shouldn't have to use get_sha_password
            # directly.
            enc = get_sha_password(converted['old_password'])
            if enc != user['password']:
                raise CustomInvalid({'old_password': 'Incorrect password'})

            users.change_password(userid, converted['password'])

            # send email
            mail = email.message.Message()
            admin_email = get_setting(context, 'admin_email')
            mail["From"] = "KARL Administrator <%s>" % admin_email
            mail["To"] = "%s <%s>" % (context.title, context.email)
            mail["Subject"] = "KARL Password Change Notification"
            body = render_template(
                "templates/email_change_password.pt",
                login=user['login'],
                password=converted['password'],
            )
            
            if isinstance(body, unicode):
                body = body.encode("UTF-8")
                
            mail.set_payload(body, "UTF-8")
            mail.set_type("text/html")

            recipients = [context.email]
            mailer = getUtility(IMailDelivery)
            mailer.send(admin_email, recipients, mail.as_string())

            path = model_url(context, request)
            msg = '?status_message=Password%20changed'
            return HTTPFound(location=path+msg)

        except Invalid, e:
            fielderrors = e.error_dict
            form.is_valid = False
    else:
        fielderrors = {}

    page_title = 'Change Password'
    api = TemplateAPI(context, request, page_title)

    form_html = render_template(
        'templates/form_change_password.pt',
        post_url=request.url,
        formfields=api.formfields,
        fielderrors=fielderrors,
        api=api,
    )

    # never prefill this form
    form.rendered_form = form_html

    return render_template_to_response(
        'templates/change_password.pt',
        form=form,
        api=api,
        )

class ChangePasswordForm(baseforms.BaseForm):
    old_password = baseforms.old_password
    password = baseforms.password
    password_confirm = baseforms.password_confirm
    chained_validators = baseforms.chained_validators