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

"""
Define interfaces for adapters that allow import and export of content into
and out of Karl.
"""

from zope.interface import Interface

class IContentIn(Interface):
    """
    An adapter interface that can be used to create or update content in Karl
    from an XML representation.  Adapters adapt an lxml.etree.Element which
    represents the root node of the XML tree for the content being imported.
    Adapters are registered as named adapters using the namespace of the root
    element as the name.  For example, let's say the following XML snippet
    defines a content object to be imported:

    <profile xmlns="http://xml.karlproject.org/profile">
      <username>crossi</username>
      <firstname>Chris</firstname>
      <lastname>Rossi</lastname>
      etc...
    </profile>

    An IContentIn adapter is found by looking up an adapter from
    lxml.etree.Element to IContentIn, named
    'http://xml.karlproject.org/profile'.  Expressed in ZCML this is:

      <adapter
        for="lxml.etree.Element"
        provides="karl.cico.interfaces.IContentIn"
        factory=".profile.ProfileIn"
        name="http://xml.karlproject.org/profile"
        />

    Because the namespace is the primary key for looking up IContentIn
    implementations, it is possible to define different XML formats and
    different import adapters for the same content type, by varying the
    namespace used.
    """

    def create(container):
        """
        Creates a new content object based on the XML representation. Content
        is created inside the passed in container object.
        """

    def update(content):
        """
        Updates the passed in content object based on the XML representation.
        """

class IContentOut(Interface):
    """
    An adapter interface that can be used to generate an XML representation of
    a content object.  For the same content type, a complementary pair of
    IContentIn and IContentOut adapters should be able to round trip their
    content.  In other words, the XML generated by an IContentOut adapter
    should be importable by a complementary IContentIn adapter.

    In order to create parallellism with IContentIn, instances of IContentOut
    may be registered by name, using the namespace as the name.  This makes it
    possible maintain different complementary pairs of adapters for the same
    content type.  Because adaptation is performed on the conte type, though,
    use of named adapters is optional.
    """
    def __call__():
        """
        Returns an lxml.etree.Element which is the XML representation of the
        adapted content.  Serialization of the XML is left to the caller.
        """