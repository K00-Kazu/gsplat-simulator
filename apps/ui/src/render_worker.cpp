#include "render_worker.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QMetaType>
#include <QStringLiteral>

#include <exception>
#include <mutex>
#include <utility>
#include <vector>

#if GSPLAT_UI_WITH_ZENOH
#include "zenoh.hxx"
#endif

namespace
{
constexpr auto kTransportConfigPath = GSPLAT_UI_TRANSPORT_CONFIG_PATH;
constexpr auto kRgb8BytesPerPixel = 3;

#if GSPLAT_UI_WITH_ZENOH
struct UiTransportTopicKeyExprs
{
    QString frameMetadata;
    QString framePayload;
    QString previewCameraState;
    QString previewSettings;
    QString cameraCommand;
};

QJsonObject loadTransportConfigObject(QString* errorDetail)
{
    QFile file(QString::fromUtf8(kTransportConfigPath));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Failed to open transport config: %1").arg(file.errorString());
        }
        throw std::runtime_error("failed to open transport config");
    }

    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parse_error);
    if (parse_error.error != QJsonParseError::NoError || !document.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Invalid transport config JSON: %1").arg(parse_error.errorString());
        }
        throw std::runtime_error("failed to parse transport config json");
    }

    return document.object();
}

zenoh::Config buildZenohConfigFromTransportConfig(const QJsonObject& transportConfig, QString* errorDetail)
{
    const QJsonValue zenoh_value = transportConfig.value(QStringLiteral("zenoh"));
    if (!zenoh_value.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Transport config does not contain a `zenoh` object.");
        }
        throw std::runtime_error("transport config is missing zenoh section");
    }

    const QByteArray zenoh_json = QJsonDocument(zenoh_value.toObject()).toJson(QJsonDocument::Compact);
    return zenoh::Config::from_str(zenoh_json.toStdString());
}

QString buildTopicError(QStringView path, QStringView detail)
{
    return QStringLiteral("Transport config `%1` %2.").arg(path, detail);
}

QString requireStringTopic(
    const QJsonObject& object,
    QStringView fieldName,
    QStringView path,
    QString* errorDetail)
{
    const QJsonValue value = object.value(fieldName.toString());
    if (!value.isString())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(path, QStringLiteral("must be a string"));
        }
        throw std::runtime_error("transport config topic must be a string");
    }

    const QString topic = value.toString();
    if (topic.isEmpty())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(path, QStringLiteral("must not be empty"));
        }
        throw std::runtime_error("transport config topic must not be empty");
    }

    return topic;
}

QString resolvePreviewTopicKeyExpr(
    const QJsonObject& uiTopics,
    QStringView exactFieldName,
    QStringView suffix,
    QString* errorDetail)
{
    const QJsonValue exactValue = uiTopics.value(exactFieldName.toString());
    if (exactValue.isString())
    {
        const QString exactTopic = exactValue.toString();
        if (!exactTopic.isEmpty())
        {
            return exactTopic;
        }
    }

    const QString previewWildcard =
        requireStringTopic(uiTopics, QStringLiteral("preview"), QStringLiteral("topics.ui.preview"), errorDetail);
    if (!previewWildcard.endsWith(QStringLiteral("/**")))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(
                QStringLiteral("topics.ui.preview"),
                QStringLiteral("must end with `/**` when exact preview topics are omitted"));
        }
        throw std::runtime_error("transport config preview topic must be a wildcard");
    }

    return previewWildcard.chopped(3) + QStringLiteral("/%1").arg(suffix);
}

QString resolveCommandTopicKeyExpr(
    const QJsonObject& uiTopics,
    QStringView exactFieldName,
    QStringView suffix,
    QString* errorDetail)
{
    const QJsonValue exactValue = uiTopics.value(exactFieldName.toString());
    if (exactValue.isString())
    {
        const QString exactTopic = exactValue.toString();
        if (!exactTopic.isEmpty())
        {
            return exactTopic;
        }
    }

    const QString commandWildcard =
        requireStringTopic(uiTopics, QStringLiteral("command"), QStringLiteral("topics.ui.command"), errorDetail);
    if (!commandWildcard.endsWith(QStringLiteral("/**")))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(
                QStringLiteral("topics.ui.command"),
                QStringLiteral("must end with `/**` when exact camera command topics are omitted"));
        }
        throw std::runtime_error("transport config ui command topic must be a wildcard");
    }

    return commandWildcard.chopped(3) + QStringLiteral("/%1").arg(suffix);
}

QString resolveStateTopicKeyExpr(
    const QJsonObject& uiTopics,
    QStringView exactFieldName,
    QStringView suffix,
    QString* errorDetail)
{
    const QJsonValue exactValue = uiTopics.value(exactFieldName.toString());
    if (exactValue.isString())
    {
        const QString exactTopic = exactValue.toString();
        if (!exactTopic.isEmpty())
        {
            return exactTopic;
        }
    }

    const QString stateWildcard =
        requireStringTopic(uiTopics, QStringLiteral("state"), QStringLiteral("topics.ui.state"), errorDetail);
    if (!stateWildcard.endsWith(QStringLiteral("/**")))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(
                QStringLiteral("topics.ui.state"),
                QStringLiteral("must end with `/**` when exact UI state topics are omitted"));
        }
        throw std::runtime_error("transport config ui state topic must be a wildcard");
    }

    return stateWildcard.chopped(3) + QStringLiteral("/%1").arg(suffix);
}

UiTransportTopicKeyExprs loadUiTransportTopicKeyExprs(
    const QJsonObject& transportConfig,
    QString* errorDetail)
{
    const QJsonValue topicsValue = transportConfig.value(QStringLiteral("topics"));
    if (!topicsValue.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(QStringLiteral("topics"), QStringLiteral("must be an object"));
        }
        throw std::runtime_error("transport config is missing topics object");
    }

    const QJsonValue uiValue = topicsValue.toObject().value(QStringLiteral("ui"));
    if (!uiValue.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = buildTopicError(QStringLiteral("topics.ui"), QStringLiteral("must be an object"));
        }
        throw std::runtime_error("transport config is missing ui topics object");
    }

    const QJsonObject uiTopics = uiValue.toObject();
    return UiTransportTopicKeyExprs{
        resolvePreviewTopicKeyExpr(
            uiTopics,
            QStringLiteral("preview_metadata"),
            QStringLiteral("frame_metadata"),
            errorDetail),
        resolvePreviewTopicKeyExpr(
            uiTopics,
            QStringLiteral("preview_payload"),
            QStringLiteral("frame_payload"),
            errorDetail),
        resolvePreviewTopicKeyExpr(
            uiTopics,
            QStringLiteral("preview_camera_state"),
            QStringLiteral("camera_state"),
            errorDetail),
        resolveStateTopicKeyExpr(
            uiTopics,
            QStringLiteral("preview_settings_state"),
            QStringLiteral("preview_settings"),
            errorDetail),
        resolveCommandTopicKeyExpr(
            uiTopics,
            QStringLiteral("camera_command"),
            QStringLiteral("camera"),
            errorDetail),
    };
}
#endif

QString buildMetadataDetail(const RenderWorker::FrameMetadata& metadata)
{
    return QStringLiteral(
               "frame_id=%1 timestamp=%2 size=%3x%4 stride=%5 pixel_format=%6")
        .arg(metadata.frameId)
        .arg(metadata.timestamp)
        .arg(metadata.width)
        .arg(metadata.height)
        .arg(metadata.stride)
        .arg(metadata.pixelFormat);
}

std::optional<QVector3D> parseVector3(const QJsonValue& value)
{
    if (!value.isArray())
    {
        return std::nullopt;
    }

    const QJsonArray array = value.toArray();
    if (array.size() != 3 || !array[0].isDouble() || !array[1].isDouble() || !array[2].isDouble())
    {
        return std::nullopt;
    }

    return QVector3D(
        static_cast<float>(array[0].toDouble()),
        static_cast<float>(array[1].toDouble()),
        static_cast<float>(array[2].toDouble()));
}

std::optional<RenderWorker::FrameMetadata> parseFrameMetadata(const QString& payloadText, QString* errorDetail)
{
    QJsonParseError parse_error;
    const QJsonDocument document =
        QJsonDocument::fromJson(payloadText.toUtf8(), &parse_error);

    if (parse_error.error != QJsonParseError::NoError || !document.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Invalid frame metadata JSON: %1").arg(parse_error.errorString());
        }
        return std::nullopt;
    }

    const QJsonObject object = document.object();

    const QJsonValue frameIdValue = object.value(QStringLiteral("frame_id"));
    const QJsonValue timestampValue = object.value(QStringLiteral("timestamp"));
    const QJsonValue widthValue = object.value(QStringLiteral("width"));
    const QJsonValue heightValue = object.value(QStringLiteral("height"));
    const QJsonValue strideValue = object.value(QStringLiteral("stride"));
    const QJsonValue pixelFormatValue = object.value(QStringLiteral("pixel_format"));

    if (!frameIdValue.isDouble() || !timestampValue.isString() || !widthValue.isDouble() || !heightValue.isDouble() ||
        !strideValue.isDouble() || !pixelFormatValue.isString())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Frame metadata is missing required fields.");
        }
        return std::nullopt;
    }

    const qint64 frame_id = frameIdValue.toVariant().toLongLong();
    const QString timestamp = timestampValue.toString();
    const int width = widthValue.toInt(-1);
    const int height = heightValue.toInt(-1);
    const int stride = strideValue.toInt(-1);
    const QString pixel_format = pixelFormatValue.toString();

    if (frame_id < 0 || timestamp.isEmpty() || width <= 0 || height <= 0 || stride <= 0 || pixel_format.isEmpty())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Frame metadata is missing required fields.");
        }
        return std::nullopt;
    }

    RenderWorker::FrameMetadata metadata;
    metadata.frameId = frame_id;
    metadata.timestamp = timestamp;
    metadata.width = width;
    metadata.height = height;
    metadata.stride = stride;
    metadata.pixelFormat = pixel_format;
    return metadata;
}

std::optional<PreviewCameraState> parsePreviewCameraState(const QString& payloadText, QString* errorDetail)
{
    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(payloadText.toUtf8(), &parse_error);

    if (parse_error.error != QJsonParseError::NoError || !document.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Invalid preview camera state JSON: %1").arg(parse_error.errorString());
        }
        return std::nullopt;
    }

    const QJsonObject object = document.object();
    const auto eye = parseVector3(object.value(QStringLiteral("eye")));
    const auto target = parseVector3(object.value(QStringLiteral("target")));
    const auto up = parseVector3(object.value(QStringLiteral("up")));
    const auto scene_center = parseVector3(object.value(QStringLiteral("scene_center")));

    const QJsonValue frame_id_value = object.value(QStringLiteral("frame_id"));
    const QJsonValue timestamp_value = object.value(QStringLiteral("timestamp"));
    const QJsonValue camera_role_value = object.value(QStringLiteral("camera_role"));
    const QJsonValue scene_radius_value = object.value(QStringLiteral("scene_radius"));
    const QJsonValue focal_length_value = object.value(QStringLiteral("focal_length_px"));
    const QJsonValue image_width_value = object.value(QStringLiteral("image_width"));
    const QJsonValue image_height_value = object.value(QStringLiteral("image_height"));
    const QJsonValue world_up_axis_value = object.value(QStringLiteral("world_up_axis"));
    const QJsonValue gizmo_enabled_value = object.value(QStringLiteral("gizmo_enabled"));

    if (!frame_id_value.isDouble() || !timestamp_value.isString() || !camera_role_value.isString() ||
        !scene_radius_value.isDouble() || !focal_length_value.isDouble() || !image_width_value.isDouble() ||
        !image_height_value.isDouble() || !world_up_axis_value.isString() || !gizmo_enabled_value.isBool() ||
        !eye.has_value() || !target.has_value() || !up.has_value() || !scene_center.has_value())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Preview camera state is missing required fields.");
        }
        return std::nullopt;
    }

    PreviewCameraState state;
    state.frameId = frame_id_value.toVariant().toLongLong();
    state.timestamp = timestamp_value.toString();
    state.cameraRole = camera_role_value.toString();
    state.eye = *eye;
    state.target = *target;
    state.up = *up;
    state.sceneCenter = *scene_center;
    state.sceneRadius = static_cast<float>(scene_radius_value.toDouble(-1.0));
    state.focalLengthPx = static_cast<float>(focal_length_value.toDouble(-1.0));
    state.imageWidth = image_width_value.toInt(-1);
    state.imageHeight = image_height_value.toInt(-1);
    state.worldUpAxis = world_up_axis_value.toString();
    state.gizmoEnabled = gizmo_enabled_value.toBool();

    if (state.frameId < 0 || state.timestamp.isEmpty() || state.cameraRole.isEmpty() || state.sceneRadius <= 0.0f ||
        state.focalLengthPx <= 0.0f || state.imageWidth <= 0 || state.imageHeight <= 0 || state.worldUpAxis.isEmpty())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Preview camera state is missing required fields.");
        }
        return std::nullopt;
    }

    return state;
}

std::optional<PreviewSettingsState> parsePreviewSettingsState(const QString& payloadText, QString* errorDetail)
{
    QJsonParseError parse_error;
    const QJsonDocument document = QJsonDocument::fromJson(payloadText.toUtf8(), &parse_error);

    if (parse_error.error != QJsonParseError::NoError || !document.isObject())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Invalid preview settings JSON: %1").arg(parse_error.errorString());
        }
        return std::nullopt;
    }

    const QJsonObject object = document.object();
    const QJsonValue ply_path_value = object.value(QStringLiteral("ply_path"));
    const QJsonValue focal_length_value = object.value(QStringLiteral("focal_length_px"));
    if (!ply_path_value.isString() || !focal_length_value.isDouble())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Preview settings are missing required fields.");
        }
        return std::nullopt;
    }

    PreviewSettingsState state;
    state.plyPath = ply_path_value.toString().trimmed();
    state.focalLengthPx = static_cast<float>(focal_length_value.toDouble(-1.0));
    if (state.plyPath.isEmpty() || state.focalLengthPx <= 0.0f)
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Preview settings are missing required fields.");
        }
        return std::nullopt;
    }

    return state;
}

QImage buildFrameImage(const RenderWorker::FrameMetadata& metadata, const std::vector<uint8_t>& payload, QString* errorDetail)
{
    if (metadata.pixelFormat != QStringLiteral("rgb8"))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Unsupported pixel_format: %1").arg(metadata.pixelFormat);
        }
        return {};
    }

    const int minimumStride = metadata.width * kRgb8BytesPerPixel;
    if (metadata.stride < minimumStride)
    {
        if (errorDetail != nullptr)
        {
            *errorDetail =
                QStringLiteral("Stride %1 is smaller than expected minimum %2.").arg(metadata.stride).arg(minimumStride);
        }
        return {};
    }

    const qint64 expectedSize = static_cast<qint64>(metadata.stride) * metadata.height;
    if (expectedSize <= 0 || expectedSize != static_cast<qint64>(payload.size()))
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Payload size %1 does not match expected size %2.")
                               .arg(static_cast<qulonglong>(payload.size()))
                               .arg(expectedSize);
        }
        return {};
    }

    const QImage image(payload.data(), metadata.width, metadata.height, metadata.stride, QImage::Format_RGB888);
    if (image.isNull())
    {
        if (errorDetail != nullptr)
        {
            *errorDetail = QStringLiteral("Failed to create QImage from frame payload.");
        }
        return {};
    }

    return image.copy();
}
}  // namespace

#if GSPLAT_UI_WITH_ZENOH
class RenderWorker::Impl
{
public:
    std::optional<zenoh::Session> session;
    std::optional<zenoh::Subscriber<void>> metadataSubscriber;
    std::optional<zenoh::Subscriber<void>> payloadSubscriber;
    std::optional<zenoh::Subscriber<void>> previewCameraStateSubscriber;
    std::optional<zenoh::Subscriber<void>> previewSettingsSubscriber;
    QString cameraCommandTopic;
    std::optional<FrameMetadata> lastFrameMetadata;
    std::optional<std::vector<uint8_t>> pendingFramePayload;
    std::mutex mutex;
    bool subscribed = false;
};
#endif

RenderWorker::RenderWorker(QObject* parent)
    : QObject(parent)
{
    qRegisterMetaType<PreviewCameraState>("PreviewCameraState");
    qRegisterMetaType<PreviewSettingsState>("PreviewSettingsState");
#if GSPLAT_UI_WITH_ZENOH
    impl_ = std::make_unique<Impl>();
#endif
}

RenderWorker::~RenderWorker() = default;

void RenderWorker::subscribe()
{
#if GSPLAT_UI_WITH_ZENOH
    if (impl_->subscribed)
    {
        emitStatus(
            QStringLiteral("render subscriber: already active"),
            QStringLiteral("The UI is already subscribed to preview frame and camera state topics."),
            false);
        return;
    }

    try
    {
#ifdef ZENOHCXX_ZENOHC
        zenoh::init_log_from_env_or("error");
#endif

        QString configErrorDetail;
        const QJsonObject transportConfig = loadTransportConfigObject(&configErrorDetail);
        const UiTransportTopicKeyExprs topicKeyExprs =
            loadUiTransportTopicKeyExprs(transportConfig, &configErrorDetail);
        auto config = buildZenohConfigFromTransportConfig(transportConfig, &configErrorDetail);
        auto session = zenoh::Session::open(std::move(config));
        const std::string frameMetadataKeyExpr = topicKeyExprs.frameMetadata.toStdString();
        const std::string framePayloadKeyExpr = topicKeyExprs.framePayload.toStdString();

        auto metadataSubscriber = session.declare_subscriber(
            zenoh::KeyExpr(frameMetadataKeyExpr),
            [this](zenoh::Sample& sample) {
                const QString payloadText = QString::fromStdString(sample.get_payload().as_string());
                QString errorDetail;
                const auto metadata = parseFrameMetadata(payloadText, &errorDetail);
                if (!metadata.has_value())
                {
                    emitStatus(
                        QStringLiteral("render subscriber: metadata parse error"),
                        errorDetail,
                        true);
                    return;
                }

                storeFrameMetadata(*metadata);
                emitStatus(
                    QStringLiteral("render subscriber: metadata received"),
                    buildMetadataDetail(*metadata),
                    false);

                const auto pendingPayload = takePendingFramePayload();
                if (pendingPayload.has_value())
                {
                    processFramePayload(*pendingPayload);
                }
            },
            [this]() {
                emitStatus(
                    QStringLiteral("render subscriber: metadata topic closed"),
                    QStringLiteral("The metadata subscriber was dropped by zenoh."),
                    true);
            });

        auto payloadSubscriber = session.declare_subscriber(
            zenoh::KeyExpr(framePayloadKeyExpr),
            [this](zenoh::Sample& sample) {
                const auto metadata = latestFrameMetadata();
                const std::vector<uint8_t> payload = sample.get_payload().as_vector();
                if (!metadata.has_value())
                {
                    storePendingFramePayload(payload);
                }
                processFramePayload(payload);
            },
            [this]() {
                emitStatus(
                    QStringLiteral("render subscriber: payload topic closed"),
                    QStringLiteral("The payload subscriber was dropped by zenoh."),
                    true);
            });

        auto previewCameraStateSubscriber = session.declare_subscriber(
            zenoh::KeyExpr(topicKeyExprs.previewCameraState.toStdString()),
            [this](zenoh::Sample& sample) {
                const QString payloadText = QString::fromStdString(sample.get_payload().as_string());
                QString errorDetail;
                const auto previewCameraState = parsePreviewCameraState(payloadText, &errorDetail);
                if (!previewCameraState.has_value())
                {
                    emitStatus(
                        QStringLiteral("preview camera state: parse error"),
                        errorDetail,
                        true);
                    return;
                }

                QMetaObject::invokeMethod(this, [this, previewCameraState = *previewCameraState]() {
                    emit previewCameraStateChanged(previewCameraState);
                });
            },
            [this]() {
                emitStatus(
                    QStringLiteral("preview camera state: topic closed"),
                    QStringLiteral("The preview camera state subscriber was dropped by zenoh."),
                    true);
            });

        auto previewSettingsSubscriber = session.declare_subscriber(
            zenoh::KeyExpr(topicKeyExprs.previewSettings.toStdString()),
            [this](zenoh::Sample& sample) {
                const QString payloadText = QString::fromStdString(sample.get_payload().as_string());
                QString errorDetail;
                const auto previewSettings = parsePreviewSettingsState(payloadText, &errorDetail);
                if (!previewSettings.has_value())
                {
                    emitStatus(
                        QStringLiteral("preview settings: parse error"),
                        errorDetail,
                        true);
                    return;
                }

                QMetaObject::invokeMethod(this, [this, previewSettings = *previewSettings]() {
                    emit previewSettingsChanged(previewSettings);
                });
            },
            [this]() {
                emitStatus(
                    QStringLiteral("preview settings: topic closed"),
                    QStringLiteral("The preview settings subscriber was dropped by zenoh."),
                    true);
            });

        impl_->session = std::move(session);
        impl_->metadataSubscriber = std::move(metadataSubscriber);
        impl_->payloadSubscriber = std::move(payloadSubscriber);
        impl_->previewCameraStateSubscriber = std::move(previewCameraStateSubscriber);
        impl_->previewSettingsSubscriber = std::move(previewSettingsSubscriber);
        impl_->cameraCommandTopic = topicKeyExprs.cameraCommand;
        impl_->subscribed = true;

        emitStatus(
            QStringLiteral("render subscriber: listening"),
            QStringLiteral("Subscribed preview frame, camera state, and preview settings topics using the `zenoh` section from `%1`.")
                .arg(QString::fromUtf8(kTransportConfigPath)),
            false);
    }
    catch (const std::exception& exception)
    {
        emitStatus(
            QStringLiteral("render subscriber: subscribe failed"),
            QStringLiteral("Exception: %1").arg(QString::fromUtf8(exception.what())),
            true);
    }
    catch (...)
    {
        emitStatus(
            QStringLiteral("render subscriber: subscribe failed"),
            QStringLiteral("An unknown exception was raised while creating the zenoh subscribers."),
            true);
    }
#else
    emitStatus(
        QStringLiteral("render subscriber: disabled"),
        QStringLiteral("Configure CMake with GSPLAT_UI_ENABLE_ZENOH=ON to enable frame subscriptions."),
        true);
#endif
}

void RenderWorker::requestPreviewRenderCommand(
    float panX,
    float panY,
    float panZ,
    float yawDegrees,
    float pitchDegrees,
    float focalLengthPx,
    const QString& plyPath)
{
#if GSPLAT_UI_WITH_ZENOH
    if (!impl_->session.has_value() || impl_->cameraCommandTopic.isEmpty())
    {
        emitStatus(
            QStringLiteral("camera command: unavailable"),
            QStringLiteral("The camera command publisher is not ready yet."),
            true);
        return;
    }

    QJsonObject payload{
        {QStringLiteral("pan_x"), panX},
        {QStringLiteral("pan_y"), panY},
        {QStringLiteral("pan_z"), panZ},
        {QStringLiteral("yaw_degrees"), yawDegrees},
        {QStringLiteral("pitch_degrees"), pitchDegrees},
    };
    if (focalLengthPx > 0.0f)
    {
        payload.insert(QStringLiteral("focal_length_px"), focalLengthPx);
    }
    if (!plyPath.trimmed().isEmpty())
    {
        payload.insert(QStringLiteral("ply_path"), plyPath);
    }

    try
    {
        const QByteArray payloadText = QJsonDocument(payload).toJson(QJsonDocument::Compact);
        impl_->session->put(
            impl_->cameraCommandTopic.toStdString(),
            payloadText.toStdString());
    }
    catch (const std::exception& exception)
    {
        emitStatus(
            QStringLiteral("camera command: send failed"),
            QStringLiteral("Exception: %1").arg(QString::fromUtf8(exception.what())),
            true);
    }
    catch (...)
    {
        emitStatus(
            QStringLiteral("camera command: send failed"),
            QStringLiteral("An unknown exception was raised while sending the camera command."),
            true);
    }
#else
    Q_UNUSED(panX);
    Q_UNUSED(panY);
    Q_UNUSED(panZ);
    Q_UNUSED(yawDegrees);
    Q_UNUSED(pitchDegrees);
    Q_UNUSED(focalLengthPx);
    Q_UNUSED(plyPath);
    emitStatus(
        QStringLiteral("camera command: disabled"),
        QStringLiteral("Configure CMake with GSPLAT_UI_ENABLE_ZENOH=ON to enable camera commands."),
        true);
#endif
}

void RenderWorker::requestPreviewSettingsUpdate(float focalLengthPx, const QString& plyPath)
{
#if GSPLAT_UI_WITH_ZENOH
    if (!impl_->session.has_value() || impl_->cameraCommandTopic.isEmpty())
    {
        emitStatus(
            QStringLiteral("camera command: unavailable"),
            QStringLiteral("The camera command publisher is not ready yet."),
            true);
        return;
    }

    QJsonObject payload;
    if (focalLengthPx > 0.0f)
    {
        payload.insert(QStringLiteral("focal_length_px"), focalLengthPx);
    }
    if (!plyPath.trimmed().isEmpty())
    {
        payload.insert(QStringLiteral("ply_path"), plyPath);
    }

    try
    {
        const QByteArray payloadText = QJsonDocument(payload).toJson(QJsonDocument::Compact);
        impl_->session->put(
            impl_->cameraCommandTopic.toStdString(),
            payloadText.toStdString());
    }
    catch (const std::exception& exception)
    {
        emitStatus(
            QStringLiteral("camera command: send failed"),
            QStringLiteral("Exception: %1").arg(QString::fromUtf8(exception.what())),
            true);
    }
    catch (...)
    {
        emitStatus(
            QStringLiteral("camera command: send failed"),
            QStringLiteral("An unknown exception was raised while sending the camera command."),
            true);
    }
#else
    Q_UNUSED(focalLengthPx);
    Q_UNUSED(plyPath);
    emitStatus(
        QStringLiteral("camera command: disabled"),
        QStringLiteral("Configure CMake with GSPLAT_UI_ENABLE_ZENOH=ON to enable camera commands."),
        true);
#endif
}

void RenderWorker::requestPreviewCameraControl(
    float panX,
    float panY,
    float panZ,
    float yawDegrees,
    float pitchDegrees)
{
    requestPreviewRenderCommand(
        panX,
        panY,
        panZ,
        yawDegrees,
        pitchDegrees,
        0.0f,
        QString());
}

void RenderWorker::requestCameraOffset(float offsetX, float offsetY, float offsetZ)
{
    requestPreviewCameraControl(offsetX, offsetY, offsetZ, 0.0f, 0.0f);
}

void RenderWorker::emitStatus(const QString& summary, const QString& detail, bool isError)
{
    QMetaObject::invokeMethod(this, [this, summary, detail, isError]() {
        emit statusChanged(summary, detail, isError);
    });
}

void RenderWorker::storeFrameMetadata(const FrameMetadata& metadata)
{
#if GSPLAT_UI_WITH_ZENOH
    std::scoped_lock lock(impl_->mutex);
    impl_->lastFrameMetadata = metadata;
#else
    Q_UNUSED(metadata);
#endif
}

void RenderWorker::storePendingFramePayload(const std::vector<uint8_t>& payload)
{
#if GSPLAT_UI_WITH_ZENOH
    std::scoped_lock lock(impl_->mutex);
    impl_->pendingFramePayload = payload;
#else
    Q_UNUSED(payload);
#endif
}

void RenderWorker::processFramePayload(const std::vector<uint8_t>& payload)
{
    const auto metadata = latestFrameMetadata();
    if (!metadata.has_value())
    {
        emitStatus(
            QStringLiteral("render subscriber: waiting for metadata"),
            QStringLiteral("Buffering the latest frame payload until metadata arrives."),
            false);
        return;
    }

    QString errorDetail;
    const QImage image = buildFrameImage(*metadata, payload, &errorDetail);
    if (image.isNull())
    {
        emitStatus(
            QStringLiteral("render subscriber: frame decode error"),
            errorDetail,
            true);
        return;
    }

#if GSPLAT_UI_WITH_ZENOH
    {
        std::scoped_lock lock(impl_->mutex);
        impl_->pendingFramePayload.reset();
    }
#endif

    QMetaObject::invokeMethod(this, [this, image, metadata = *metadata]() {
        emit frameReady(image, metadata.frameId);
        emit statusChanged(
            QStringLiteral("render subscriber: frame displayed"),
            buildMetadataDetail(metadata),
            false);
    });
}

std::optional<RenderWorker::FrameMetadata> RenderWorker::latestFrameMetadata() const
{
#if GSPLAT_UI_WITH_ZENOH
    std::scoped_lock lock(impl_->mutex);
    return impl_->lastFrameMetadata;
#else
    return std::nullopt;
#endif
}

std::optional<std::vector<uint8_t>> RenderWorker::takePendingFramePayload()
{
#if GSPLAT_UI_WITH_ZENOH
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->pendingFramePayload.has_value())
    {
        return std::nullopt;
    }

    auto payload = impl_->pendingFramePayload;
    impl_->pendingFramePayload.reset();
    return payload;
#else
    return std::nullopt;
#endif
}
