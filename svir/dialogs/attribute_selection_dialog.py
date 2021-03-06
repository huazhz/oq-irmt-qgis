# -*- coding: utf-8 -*-
# /***************************************************************************
# Irmt
#                                 A QGIS plugin
# OpenQuake Integrated Risk Modelling Toolkit
#                              -------------------
#        begin                : 2013-10-24
#        copyright            : (C) 2013-2015 by GEM Foundation
#        email                : devops@openquake.org
# ***************************************************************************/
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

from qgis.PyQt.QtCore import pyqtSlot
from qgis.PyQt.QtGui import (QDialog,
                             QDialogButtonBox,
                             )

from svir.utilities.utils import tr, get_ui_class
from svir.utilities.shared import NUMERIC_FIELD_TYPES

FORM_CLASS = get_ui_class('ui_attribute_selection.ui')


class AttributeSelectionDialog(QDialog, FORM_CLASS):
    """
    Modal dialog giving to the user the possibility to select
    what are the attributes, in the loss layer and in the region layer,
    that contain the loss data and the region id
    """
    def __init__(self, loss_layer, zonal_layer):
        QDialog.__init__(self)
        # Set up the user interface from Designer.
        self.setupUi(self)
        self.ok_button = self.buttonBox.button(QDialogButtonBox.Ok)
        self.set_ok_button()

        # if the loss layer does not contain an attribute specifying the ids of
        # zones, the user must not be forced to select such attribute, so we
        # add an "empty" option to the combobox
        self.zone_id_attr_name_loss_cbox.addItem(
            tr("Use zonal geometries"))

        # if the zonal_layer doesn't have a field containing a unique zone id,
        # the user can choose to add such unique id
        self.zone_id_attr_name_zone_cbox.addItem(
            tr("Add field with unique zone id"))

        # Load in the comboboxes only the names of the attributes compatible
        # with the following analyses
        for field in loss_layer.fields():
            # for the zone id accept both numeric or textual fields
            self.zone_id_attr_name_loss_cbox.addItem(field.name())
            # Accept only numeric fields to contain loss data
            if field.typeName() in NUMERIC_FIELD_TYPES:
                self.loss_attrs_multisel.add_unselected_items(
                    [field.name()])

        self.zone_id_attr_name_loss_cbox.setCurrentIndex(0)

        for field in zonal_layer.fields():
            # for the zone id accept both numeric or textual fields
            self.zone_id_attr_name_zone_cbox.addItem(field.name())
            # by default, set the selection to the first textual field

        self.zone_id_attr_name_zone_cbox.setCurrentIndex(0)

        self.loss_attrs_multisel.selection_changed.connect(
            self.set_ok_button)

    def set_ok_button(self):
        self.ok_button.setEnabled(
            self.loss_attrs_multisel.selected_widget.count() > 0)

    def accept(self):
        # retrieve attribute names from selections
        loss_attr_names = \
            list(self.loss_attrs_multisel.get_selected_items())
        # index 0 is for "use zonal geometries" (no zone id available)
        if self.zone_id_attr_name_loss_cbox.currentIndex() == 0:
            zone_id_in_losses_attr_name = None
        else:
            zone_id_in_losses_attr_name = \
                self.zone_id_attr_name_loss_cbox.currentText()
        # index 0 is for "Add field with unique zone id"
        if self.zone_id_attr_name_zone_cbox.currentIndex() == 0:
            zone_id_in_zones_attr_name = None
        else:
            zone_id_in_zones_attr_name = \
                self.zone_id_attr_name_zone_cbox.currentText()
        self.selected_attributes = (loss_attr_names,
                                    zone_id_in_losses_attr_name,
                                    zone_id_in_zones_attr_name)

        super(AttributeSelectionDialog, self).accept()

    @pyqtSlot(int)
    def on_zone_id_attr_name_zone_cbox_currentIndexChanged(self, new_index):
        if new_index == 0:
            self.zone_id_attr_name_loss_cbox.setCurrentIndex(0)
            self.zone_id_attr_name_loss_cbox.setDisabled(True)
        else:
            self.zone_id_attr_name_loss_cbox.setDisabled(False)
