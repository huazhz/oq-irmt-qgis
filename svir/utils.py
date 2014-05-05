# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Svir
                                 A QGIS plugin
 OpenQuake Social Vulnerability and Integrated Risk
                              -------------------
        begin                : 2013-10-24
        copyright            : (C) 2013 by GEM Foundation
        email                : devops@openquake.org
 ***************************************************************************/

# Copyright (c) 2010-2013, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.
"""
import collections
from time import time
from PyQt4.QtCore import QSettings, Qt
from PyQt4.QtGui import QApplication
from qgis.core import QgsMapLayerRegistry
from settings_dialog import SettingsDialog
from qgis.gui import QgsMessageBar


def tr(message):
    return QApplication.translate('Svir', message)


def get_credentials(iface):
    qs = QSettings()
    hostname = qs.value('svir/platform_hostname', '')
    username = qs.value('svir/platform_username', '')
    password = qs.value('svir/platform_password', '')
    if not (hostname and username and password):
        SettingsDialog(iface).exec_()
        hostname = qs.value('svir/platform_hostname', '')
        username = qs.value('svir/platform_username', '')
        password = qs.value('svir/platform_password', '')
    return hostname, username, password


def assign_default_weights(svi_themes):
    # count themes and indicators and assign default weights
    # using 2 decimal points (%.2f)
    themes_count = len(svi_themes)
    theme_weight = float('%.2f' % (1.0 / themes_count))
    for i, theme in enumerate(svi_themes):
        theme['weight'] = theme_weight
        for indicator in theme['children']:
            indicator_weight = 1.0 / len(theme['children'])
            indicator_weight = '%.2f' % indicator_weight
            indicator['weight'] = float(indicator_weight)


def reload_layers_in_cbx(combo, *valid_layer_types):
    """
    Load layers into a combobox. Can filter by layer type.
    the additional filter can be QgsMapLayer.VectorLayer, ...

    :param combo: The combobox to be repopulated
    :type combo: QComboBox
    :param *valid_layer_types: multiple tuples containing types
    :type *valid_layer_types: QgsMapLayer.LayerType, ...
    """
    layer_types = set()
    for layer_type in valid_layer_types:
        layer_types.update([layer_type])
    combo.clear()
    for l in QgsMapLayerRegistry.instance().mapLayers().values():
        if not layer_types or l.type() in layer_types:
            combo.addItem(l.name())


def reload_attrib_cbx(combo, layer, *valid_field_types):
    """
    Load attributes of a layer into a combobox. Can filter by field data type.
    the additional filter can be NUMERIC_FIELD_TYPES, TEXTUAL_FIELD_TYPES, ...

    :param combo: The combobox to be repopulated
    :type combo: QComboBox
    :param layer: The QgsVectorLayer from where the fields are read
    :type layer: QgsVectorLayer
    :param *valid_field_types: multiple tuples containing types
    :type *valid_field_types: tuple, tuple, ...
    """
    field_types = set()
    for field_type in valid_field_types:
        field_types.update(field_type)

    # reset combo box
    combo.clear()
    # populate combo box with field names taken by layers
    dp = layer.dataProvider()
    fields = list(dp.fields())
    for field in fields:
        # add if in field_types
        if not field_types or field.typeName() in field_types:
            combo.addItem(field.name())


class Register(collections.OrderedDict):
    """
    Useful to keep (in a single point) a register of available variants of
    something, e.g. a set of different normalization/standardization algorithms
    """
    def add(self, tag):
        """
        Add a new variant to the OrderedDict
        For instance, if we add a class implementing a specific normalization
        algorithm, the register will keep track of a new item having as key the
        name of the algorithm and as value the class implementing the algorithm
        """
        def dec(obj):
            self[tag] = obj
            return obj
        return dec


class TraceTimeManager(object):
    def __init__(self, message, debug=False):
        self.debug = debug
        self.message = message
        self.t_start = None
        self.t_stop = None

    def __enter__(self):
        if self.debug:
            print self.message
            self.t_start = time()

    def __exit__(self, type, value, traceback):
        if self.debug:
            self.t_stop = time()
            print "Completed in %f" % (self.t_stop - self.t_start)


class LayerEditingManager(object):
    def __init__(self, layer, message, debug=False):
        self.layer = layer
        self.message = message
        self.debug = debug

    def __enter__(self):
        self.layer.startEditing()
        if self.debug:
            print "BEGIN", self.message

    def __exit__(self, type, value, traceback):
        self.layer.commitChanges()
        self.layer.updateExtents()
        if self.debug:
            print "END", self.message


class WaitCursorManager(object):
    def __init__(self, msg=None, iface=None):
        self.msg = msg
        self.iface = iface
        self.has_message = msg and iface
        self.message = None

    def __enter__(self):
        if self.has_message:
            self.message = self.iface.messageBar().createMessage(
                tr('Info'), tr(self.msg))
            self.message = self.iface.messageBar().pushWidget(
                self.message, level=QgsMessageBar.INFO)
            QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, type, value, traceback):
        QApplication.restoreOverrideCursor()
        if self.has_message:
            self.iface.messageBar().popWidget(self.message)
