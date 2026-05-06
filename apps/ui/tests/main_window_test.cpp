#include "main_window.h"
#include "preview_viewport_widget.h"
#include "render_worker.h"

#include <QAction>
#include <QBoxLayout>
#include <QDockWidget>
#include <QFrame>
#include <QImage>
#include <QLabel>
#include <QMenuBar>
#include <QPainter>
#include <QPushButton>
#include <QStatusBar>
#include <QtTest/QtTest>

class MainWindowTest : public QObject
{
    Q_OBJECT

private slots:
    void placesCameraControlsInRightDock();
    void rendersSubscriberStatusInBottomStatusBar();
    void labelsPreviewCameraUiClearly();
    void removesCameraHelpCopyAndCompactsScenePanel();
    void separatesPanAndRotateControls();
    void exposesRobotMovementAndRotationControls();
    void exposesSceneSelectionFromMenuBar();
    void exposesOptionBCameraActionButtons();
    void fitButtonResetsPreviewCameraControls();
    void rendersPreviewGizmoWithLatestCameraStateFallback();
};

void MainWindowTest::placesCameraControlsInRightDock()
{
    MainWindow window(nullptr, false);

    auto* camera_controls_dock = window.findChild<QDockWidget*>("cameraControlsDock");
    QVERIFY(camera_controls_dock != nullptr);
    QCOMPARE(window.dockWidgetArea(camera_controls_dock), Qt::RightDockWidgetArea);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    auto* preview_controls_group = window.findChild<QFrame*>("previewControlsGroup");
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(preview_controls_group != nullptr);
    QVERIFY(preview_controls_group->isAncestorOf(camera_pan_label));
}

void MainWindowTest::rendersSubscriberStatusInBottomStatusBar()
{
    MainWindow window(nullptr, false);

    auto* status_bar = window.statusBar();
    QVERIFY(status_bar != nullptr);

    auto* render_status_label = window.findChild<QLabel*>("renderStatusLabel");
    auto* render_detail_label = window.findChild<QLabel*>("renderDetailLabel");
    QVERIFY(render_status_label != nullptr);
    QVERIFY(render_detail_label != nullptr);
    QCOMPARE(render_status_label->parentWidget(), status_bar);
    QCOMPARE(render_detail_label->parentWidget(), status_bar);
    QCOMPARE(render_status_label->text(), QString("render subscriber: starting..."));
}

void MainWindowTest::labelsPreviewCameraUiClearly()
{
    MainWindow window(nullptr, false);

    auto* camera_controls_dock = window.findChild<QDockWidget*>("cameraControlsDock");
    QVERIFY(camera_controls_dock != nullptr);
    QCOMPARE(camera_controls_dock->windowTitle(), QString("Controls"));

    auto* preview_controls_group = window.findChild<QFrame*>("previewControlsGroup");
    QVERIFY(preview_controls_group != nullptr);

    auto* preview_viewport = window.findChild<QWidget*>("previewViewport");
    QVERIFY(preview_viewport != nullptr);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(camera_pan_label->text().contains("Preview camera pan"));
}

void MainWindowTest::removesCameraHelpCopyAndCompactsScenePanel()
{
    MainWindow window(nullptr, false);

    const auto labels = window.findChildren<QLabel*>();
    for (const auto* label : labels)
    {
        QVERIFY(!label->text().startsWith("Open scenes from the File menu"));
    }

    auto* scene_card = window.findChild<QFrame*>("sceneControlCard");
    auto* current_scene_label = window.findChild<QLabel*>("currentSceneLabel");
    QVERIFY(scene_card != nullptr);
    QVERIFY(current_scene_label != nullptr);
    QVERIFY(scene_card->maximumHeight() <= 88);
    QVERIFY(!current_scene_label->wordWrap());
}

void MainWindowTest::separatesPanAndRotateControls()
{
    MainWindow window(nullptr, false);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    auto* camera_rotation_label = window.findChild<QLabel*>("cameraRotationLabel");
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(camera_rotation_label != nullptr);
    QVERIFY(camera_pan_label->text().contains("Preview camera pan"));
    QVERIFY(camera_rotation_label->text().contains("Preview camera rotation"));

    auto* pan_up_button = window.findChild<QPushButton*>("panUpButton");
    auto* rotate_up_button = window.findChild<QPushButton*>("rotateUpButton");
    QVERIFY(pan_up_button != nullptr);
    QVERIFY(rotate_up_button != nullptr);
    QVERIFY(pan_up_button->property("controlRingButton").toBool());
    QVERIFY(rotate_up_button->property("controlRingButton").toBool());
    QVERIFY(pan_up_button->maximumWidth() <= 48);
    QVERIFY(rotate_up_button->maximumWidth() <= 48);
}

void MainWindowTest::exposesRobotMovementAndRotationControls()
{
    MainWindow window(nullptr, false);

    auto* robot_pose_label = window.findChild<QLabel*>("robotPoseLabel");
    auto* preview_controls_group = window.findChild<QFrame*>("previewControlsGroup");
    auto* controls_body = window.findChild<QWidget*>("controlsBody");
    auto* robot_card = window.findChild<QFrame*>("robotControlCard");
    auto* robot_forward_button = window.findChild<QPushButton*>("robotForwardButton");
    auto* robot_back_button = window.findChild<QPushButton*>("robotBackButton");
    auto* robot_left_button = window.findChild<QPushButton*>("robotLeftButton");
    auto* robot_right_button = window.findChild<QPushButton*>("robotRightButton");
    auto* robot_rise_button = window.findChild<QPushButton*>("robotRiseButton");
    auto* robot_lower_button = window.findChild<QPushButton*>("robotLowerButton");
    auto* robot_rotate_left_button = window.findChild<QPushButton*>("robotRotateLeftButton");
    auto* robot_rotate_right_button = window.findChild<QPushButton*>("robotRotateRightButton");

    QVERIFY(preview_controls_group != nullptr);
    QVERIFY(controls_body != nullptr);
    QVERIFY(robot_card != nullptr);
    QCOMPARE(preview_controls_group->parentWidget(), controls_body);
    QCOMPARE(robot_card->parentWidget(), controls_body);
    auto* controls_layout = qobject_cast<QBoxLayout*>(controls_body->layout());
    QVERIFY(controls_layout != nullptr);
    QCOMPARE(controls_layout->direction(), QBoxLayout::LeftToRight);
    auto* robot_layout_item = controls_layout->itemAt(1);
    QVERIFY(robot_layout_item != nullptr);
    QVERIFY((robot_layout_item->alignment() & Qt::AlignTop) != 0);
    QVERIFY(robot_pose_label != nullptr);
    QVERIFY(robot_pose_label->text().contains("Robot pose"));
    QVERIFY(robot_forward_button != nullptr);
    QVERIFY(robot_back_button != nullptr);
    QVERIFY(robot_left_button != nullptr);
    QVERIFY(robot_right_button != nullptr);
    QVERIFY(robot_rise_button != nullptr);
    QVERIFY(robot_lower_button != nullptr);
    QVERIFY(robot_rotate_left_button != nullptr);
    QVERIFY(robot_rotate_right_button != nullptr);
    QVERIFY(robot_forward_button->property("controlRingButton").toBool());
    QVERIFY(robot_back_button->property("controlRingButton").toBool());
    QVERIFY(robot_left_button->property("controlRingButton").toBool());
    QVERIFY(robot_right_button->property("controlRingButton").toBool());
    QVERIFY(robot_rise_button->property("controlRingButton").toBool());
    QVERIFY(robot_lower_button->property("controlRingButton").toBool());
    QVERIFY(robot_rotate_left_button->property("controlRingButton").toBool());
    QVERIFY(robot_rotate_right_button->property("controlRingButton").toBool());
    QVERIFY(robot_forward_button->maximumWidth() <= 48);
    QVERIFY(robot_right_button->maximumWidth() <= 48);
    QVERIFY(robot_rotate_right_button->maximumWidth() <= 48);
}

void MainWindowTest::exposesSceneSelectionFromMenuBar()
{
    MainWindow window(nullptr, false);

    auto* open_scene_action = window.findChild<QAction*>("openSceneAction");
    auto* current_scene_label = window.findChild<QLabel*>("currentSceneLabel");
    auto* camera_zoom_label = window.findChild<QLabel*>("cameraZoomLabel");
    auto* legacy_scene_path_input = window.findChild<QWidget*>("previewScenePathInput");
    QVERIFY(window.menuBar() != nullptr);
    QVERIFY(open_scene_action != nullptr);
    QCOMPARE(open_scene_action->text(), QString("Open Scene..."));
    QVERIFY(current_scene_label != nullptr);
    QVERIFY(current_scene_label->text().contains("Scene:"));
    QVERIFY(camera_zoom_label != nullptr);
    QVERIFY(camera_zoom_label->text().contains("Preview zoom"));
    QVERIFY(legacy_scene_path_input == nullptr);
}

void MainWindowTest::exposesOptionBCameraActionButtons()
{
    MainWindow window(nullptr, false);

    auto* scene_view_button = window.findChild<QPushButton*>("sceneViewButton");
    auto* fit_button = window.findChild<QPushButton*>("fitSceneButton");
    auto* zoom_in_button = window.findChild<QPushButton*>("zoomInButton");
    auto* zoom_out_button = window.findChild<QPushButton*>("zoomOutButton");
    auto* pan_up_button = window.findChild<QPushButton*>("panUpButton");
    auto* pan_left_button = window.findChild<QPushButton*>("panLeftButton");
    auto* pan_right_button = window.findChild<QPushButton*>("panRightButton");
    auto* pan_down_button = window.findChild<QPushButton*>("panDownButton");
    auto* rotate_up_button = window.findChild<QPushButton*>("rotateUpButton");
    auto* rotate_left_button = window.findChild<QPushButton*>("rotateLeftButton");
    auto* rotate_right_button = window.findChild<QPushButton*>("rotateRightButton");
    auto* rotate_down_button = window.findChild<QPushButton*>("rotateDownButton");

    QVERIFY(scene_view_button != nullptr);
    QVERIFY(fit_button != nullptr);
    QVERIFY(zoom_in_button != nullptr);
    QVERIFY(zoom_out_button != nullptr);
    QVERIFY(pan_up_button != nullptr);
    QVERIFY(pan_left_button != nullptr);
    QVERIFY(pan_right_button != nullptr);
    QVERIFY(pan_down_button != nullptr);
    QVERIFY(rotate_up_button != nullptr);
    QVERIFY(rotate_left_button != nullptr);
    QVERIFY(rotate_right_button != nullptr);
    QVERIFY(rotate_down_button != nullptr);

    QCOMPARE(scene_view_button->text(), QString("Scene View"));
    QCOMPARE(fit_button->text(), QString("Fit"));
}

void MainWindowTest::fitButtonResetsPreviewCameraControls()
{
    MainWindow window(nullptr, false);

    auto* fit_button = window.findChild<QPushButton*>("fitSceneButton");
    auto* zoom_in_button = window.findChild<QPushButton*>("zoomInButton");
    auto* pan_right_button = window.findChild<QPushButton*>("panRightButton");
    auto* pan_down_button = window.findChild<QPushButton*>("panDownButton");
    auto* rotate_left_button = window.findChild<QPushButton*>("rotateLeftButton");
    auto* rotate_up_button = window.findChild<QPushButton*>("rotateUpButton");
    auto* camera_zoom_label = window.findChild<QLabel*>("cameraZoomLabel");
    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    auto* camera_rotation_label = window.findChild<QLabel*>("cameraRotationLabel");

    QVERIFY(fit_button != nullptr);
    QVERIFY(zoom_in_button != nullptr);
    QVERIFY(pan_right_button != nullptr);
    QVERIFY(pan_down_button != nullptr);
    QVERIFY(rotate_left_button != nullptr);
    QVERIFY(rotate_up_button != nullptr);
    QVERIFY(camera_zoom_label != nullptr);
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(camera_rotation_label != nullptr);

    QTest::mouseClick(zoom_in_button, Qt::LeftButton);
    QTest::mouseClick(pan_right_button, Qt::LeftButton);
    QTest::mouseClick(pan_down_button, Qt::LeftButton);
    QTest::mouseClick(rotate_left_button, Qt::LeftButton);
    QTest::mouseClick(rotate_up_button, Qt::LeftButton);

    QVERIFY(camera_zoom_label->text().contains("focal=1035.0px"));
    QVERIFY(camera_pan_label->text().contains("x=0.20 y=0.00 z=-0.20"));
    QVERIFY(camera_rotation_label->text().contains("yaw=-12.0deg pitch=12.0deg"));

    QTest::mouseClick(fit_button, Qt::LeftButton);

    QVERIFY(!fit_button->property("placeholderAction").toBool());
    QVERIFY(camera_zoom_label->text().contains("focal=900.0px"));
    QVERIFY(camera_pan_label->text().contains("x=0.00 y=0.00 z=0.00"));
    QVERIFY(camera_rotation_label->text().contains("yaw=0.0deg pitch=0.0deg"));
}

void MainWindowTest::rendersPreviewGizmoWithLatestCameraStateFallback()
{
    PreviewViewportWidget widget;
    widget.setMinimumSize(0, 0);
    widget.resize(400, 300);

    QImage preview_frame(400, 300, QImage::Format_RGB32);
    preview_frame.fill(Qt::white);
    widget.setPreviewFrame(preview_frame, 5);

    PreviewCameraState preview_camera_state;
    preview_camera_state.frameId = 4;
    preview_camera_state.cameraRole = "preview";
    preview_camera_state.eye = QVector3D(0.0f, -10.0f, 4.0f);
    preview_camera_state.target = QVector3D(0.0f, 0.0f, 0.0f);
    preview_camera_state.up = QVector3D(0.0f, 0.0f, 1.0f);
    preview_camera_state.sceneCenter = QVector3D(0.0f, 0.0f, 0.0f);
    preview_camera_state.sceneRadius = 5.0f;
    preview_camera_state.focalLengthPx = 900.0f;
    preview_camera_state.imageWidth = 400;
    preview_camera_state.imageHeight = 300;
    preview_camera_state.worldUpAxis = "z";
    preview_camera_state.gizmoEnabled = true;
    widget.setPreviewCameraState(preview_camera_state);

    QImage canvas(widget.size(), QImage::Format_ARGB32_Premultiplied);
    canvas.fill(Qt::transparent);

    QPainter painter(&canvas);
    widget.render(&painter);
    painter.end();

    const QColor sampled_color = canvas.pixelColor(widget.width() - 72, widget.height() - 72);
    QVERIFY(sampled_color != QColor(Qt::white));
}

QTEST_MAIN(MainWindowTest)

#include "main_window_test.moc"
