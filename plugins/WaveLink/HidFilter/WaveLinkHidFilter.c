#include <ntddk.h>
#include <wdf.h>
#include <hidport.h>

#include "WaveLinkHidFilter.h"

const GUID GUID_DEVINTERFACE_WAVELINK_HID_FILTER = {
    0x7d35f6e1,
    0x6a2a,
    0x4ab6,
    {0x9c, 0xf2, 0x1d, 0xf1, 0x84, 0x8c, 0x79, 0xa2}};

typedef struct _DEVICE_CONTEXT {
    WDFSPINLOCK Lock;
    BOOLEAN Enabled;
    UCHAR ReportId;
    UCHAR PayloadLength;
    UCHAR UpMask[WAVELINK_MAX_PAYLOAD];
    UCHAR DownMask[WAVELINK_MAX_PAYLOAD];
    WAVELINK_VOLUME_EVENT Events[WAVELINK_EVENT_QUEUE_SIZE];
    ULONG EventHead;
    ULONG EventCount;
    ULONG EventSequence;
    WDFFILEOBJECT ClientFile;
} DEVICE_CONTEXT, *PDEVICE_CONTEXT;

WDF_DECLARE_CONTEXT_TYPE_WITH_NAME(DEVICE_CONTEXT, DeviceGetContext)

DRIVER_INITIALIZE DriverEntry;
EVT_WDF_DRIVER_DEVICE_ADD EvtDeviceAdd;
EVT_WDF_IO_QUEUE_IO_INTERNAL_DEVICE_CONTROL EvtIoInternalDeviceControl;
EVT_WDF_IO_QUEUE_IO_DEVICE_CONTROL EvtIoDeviceControl;
EVT_WDF_REQUEST_COMPLETION_ROUTINE EvtReadReportComplete;
EVT_WDF_DEVICE_FILE_CREATE EvtDeviceFileCreate;
EVT_WDF_FILE_CLEANUP EvtFileCleanup;

static VOID
ForwardRequest(
    WDFDEVICE Device,
    WDFREQUEST Request,
    BOOLEAN InspectReport
)
{
    WDFIOTARGET target = WdfDeviceGetIoTarget(Device);

    WdfRequestFormatRequestUsingCurrentType(Request);
    if (InspectReport) {
        WdfRequestSetCompletionRoutine(
            Request,
            EvtReadReportComplete,
            Device);
    }

    if (!WdfRequestSend(Request, target, WDF_NO_SEND_OPTIONS)) {
        WdfRequestCompleteWithInformation(
            Request,
            WdfRequestGetStatus(Request),
            WdfRequestGetInformation(Request));
    }
}

NTSTATUS
DriverEntry(
    PDRIVER_OBJECT DriverObject,
    PUNICODE_STRING RegistryPath
)
{
    WDF_DRIVER_CONFIG config;
    WDF_DRIVER_CONFIG_INIT(&config, EvtDeviceAdd);
    return WdfDriverCreate(
        DriverObject,
        RegistryPath,
        WDF_NO_OBJECT_ATTRIBUTES,
        &config,
        WDF_NO_HANDLE);
}

NTSTATUS
EvtDeviceAdd(
    WDFDRIVER Driver,
    PWDFDEVICE_INIT DeviceInit
)
{
    NTSTATUS status;
    WDFDEVICE device;
    WDF_OBJECT_ATTRIBUTES deviceAttributes;
    WDF_IO_QUEUE_CONFIG queueConfig;
    WDF_OBJECT_ATTRIBUTES lockAttributes;
    WDF_FILEOBJECT_CONFIG fileConfig;
    UNREFERENCED_PARAMETER(Driver);

    WdfFdoInitSetFilter(DeviceInit);

    WDF_FILEOBJECT_CONFIG_INIT(
        &fileConfig,
        EvtDeviceFileCreate,
        WDF_NO_EVENT_CALLBACK,
        EvtFileCleanup);
    WdfDeviceInitSetFileObjectConfig(
        DeviceInit,
        &fileConfig,
        WDF_NO_OBJECT_ATTRIBUTES);

    WDF_OBJECT_ATTRIBUTES_INIT_CONTEXT_TYPE(
        &deviceAttributes,
        DEVICE_CONTEXT);
    status = WdfDeviceCreate(
        &DeviceInit,
        &deviceAttributes,
        &device);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    RtlZeroMemory(DeviceGetContext(device), sizeof(DEVICE_CONTEXT));
    WDF_OBJECT_ATTRIBUTES_INIT(&lockAttributes);
    lockAttributes.ParentObject = device;
    status = WdfSpinLockCreate(
        &lockAttributes,
        &DeviceGetContext(device)->Lock);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    status = WdfDeviceCreateDeviceInterface(
        device,
        &GUID_DEVINTERFACE_WAVELINK_HID_FILTER,
        NULL);
    if (!NT_SUCCESS(status)) {
        return status;
    }

    WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(
        &queueConfig,
        WdfIoQueueDispatchParallel);
    queueConfig.EvtIoInternalDeviceControl =
        EvtIoInternalDeviceControl;
    queueConfig.EvtIoDeviceControl = EvtIoDeviceControl;

    return WdfIoQueueCreate(
        device,
        &queueConfig,
        WDF_NO_OBJECT_ATTRIBUTES,
        WDF_NO_HANDLE);
}

VOID
EvtIoInternalDeviceControl(
    WDFQUEUE Queue,
    WDFREQUEST Request,
    size_t OutputBufferLength,
    size_t InputBufferLength,
    ULONG IoControlCode
)
{
    UNREFERENCED_PARAMETER(OutputBufferLength);
    UNREFERENCED_PARAMETER(InputBufferLength);

    ForwardRequest(
        WdfIoQueueGetDevice(Queue),
        Request,
        IoControlCode == IOCTL_HID_READ_REPORT);
}

VOID
EvtIoDeviceControl(
    WDFQUEUE Queue,
    WDFREQUEST Request,
    size_t OutputBufferLength,
    size_t InputBufferLength,
    ULONG IoControlCode
)
{
    NTSTATUS status;
    WDFDEVICE device = WdfIoQueueGetDevice(Queue);
    PDEVICE_CONTEXT context = DeviceGetContext(device);

    if (IoControlCode == IOCTL_WAVELINK_HID_SET_CONFIG) {
        PWAVELINK_HID_CONFIG config;
        size_t length;
        ULONG index;
        BOOLEAN hasUp = FALSE;
        BOOLEAN hasDown = FALSE;

        if (InputBufferLength < sizeof(WAVELINK_HID_CONFIG)) {
            WdfRequestComplete(Request, STATUS_BUFFER_TOO_SMALL);
            return;
        }

        status = WdfRequestRetrieveInputBuffer(
            Request,
            sizeof(WAVELINK_HID_CONFIG),
            (PVOID*)&config,
            &length);
        if (!NT_SUCCESS(status)) {
            WdfRequestComplete(Request, status);
            return;
        }

        if (config->PayloadLength == 0 ||
            config->PayloadLength > WAVELINK_MAX_PAYLOAD ||
            config->ReportId == 0) {
            WdfRequestComplete(Request, STATUS_INVALID_PARAMETER);
            return;
        }

        for (index = 0; index < config->PayloadLength; ++index) {
            if ((config->UpMask[index] & config->DownMask[index]) != 0) {
                WdfRequestComplete(Request, STATUS_INVALID_PARAMETER);
                return;
            }
            hasUp |= config->UpMask[index] != 0;
            hasDown |= config->DownMask[index] != 0;
        }
        if (!hasUp || !hasDown) {
            WdfRequestComplete(Request, STATUS_INVALID_PARAMETER);
            return;
        }

        WdfSpinLockAcquire(context->Lock);
        context->ReportId = config->ReportId;
        context->PayloadLength = config->PayloadLength;
        RtlCopyMemory(context->UpMask, config->UpMask, WAVELINK_MAX_PAYLOAD);
        RtlCopyMemory(context->DownMask, config->DownMask, WAVELINK_MAX_PAYLOAD);
        context->EventHead = 0;
        context->EventCount = 0;
        context->ClientFile = WdfRequestGetFileObject(Request);
        context->Enabled = TRUE;
        WdfSpinLockRelease(context->Lock);

        WdfRequestCompleteWithInformation(Request, STATUS_SUCCESS, 0);
        return;
    }

    if (IoControlCode == IOCTL_WAVELINK_HID_GET_EVENT) {
        PWAVELINK_VOLUME_EVENT volumeEvent;
        size_t length;

        if (OutputBufferLength < sizeof(WAVELINK_VOLUME_EVENT)) {
            WdfRequestComplete(Request, STATUS_BUFFER_TOO_SMALL);
            return;
        }

        status = WdfRequestRetrieveOutputBuffer(
            Request,
            sizeof(WAVELINK_VOLUME_EVENT),
            (PVOID*)&volumeEvent,
            &length);
        if (!NT_SUCCESS(status)) {
            WdfRequestComplete(Request, status);
            return;
        }

        WdfSpinLockAcquire(context->Lock);
        if (context->EventCount == 0) {
            WdfSpinLockRelease(context->Lock);
            WdfRequestComplete(Request, STATUS_NO_MORE_ENTRIES);
            return;
        }
        *volumeEvent = context->Events[context->EventHead];
        context->EventHead =
            (context->EventHead + 1) % WAVELINK_EVENT_QUEUE_SIZE;
        --context->EventCount;
        WdfSpinLockRelease(context->Lock);

        WdfRequestCompleteWithInformation(
            Request,
            STATUS_SUCCESS,
            sizeof(WAVELINK_VOLUME_EVENT));
        return;
    }

    ForwardRequest(device, Request, FALSE);
}

VOID
EvtReadReportComplete(
    WDFREQUEST Request,
    WDFIOTARGET Target,
    PWDF_REQUEST_COMPLETION_PARAMS Params,
    WDFCONTEXT ContextPointer
)
{
    WDFDEVICE device = (WDFDEVICE)ContextPointer;
    PDEVICE_CONTEXT context = DeviceGetContext(device);

    UNREFERENCED_PARAMETER(Target);

    if (NT_SUCCESS(Params->IoStatus.Status)) {
        PUCHAR report;
        size_t reportLength;
        size_t outputBufferLength;
        UCHAR upBits = 0;
        UCHAR downBits = 0;
        ULONG index;
        WAVELINK_VOLUME_EVENT volumeEvent;
        BOOLEAN sendEvent = FALSE;

        if (NT_SUCCESS(WdfRequestRetrieveOutputBuffer(
                Request,
                1,
                (PVOID*)&report,
                &outputBufferLength))) {
            reportLength = (size_t)Params->IoStatus.Information;
            if (reportLength > outputBufferLength) {
                reportLength = outputBufferLength;
            }
            WdfSpinLockAcquire(context->Lock);
            if (context->Enabled &&
                report[0] == context->ReportId &&
                reportLength >= (size_t)context->PayloadLength + 1) {
                for (index = 0; index < context->PayloadLength; ++index) {
                    upBits |= report[index + 1] & context->UpMask[index];
                    downBits |= report[index + 1] & context->DownMask[index];
                }

                if (upBits != 0 || downBits != 0) {
                    for (index = 0; index < context->PayloadLength; ++index) {
                        report[index + 1] &=
                            (UCHAR)~(context->UpMask[index] |
                                     context->DownMask[index]);
                    }

                    volumeEvent.Sequence = ++context->EventSequence;
                    volumeEvent.Direction =
                        upBits != 0 ? WAVELINK_VOLUME_UP : WAVELINK_VOLUME_DOWN;
                    if (context->EventCount == WAVELINK_EVENT_QUEUE_SIZE) {
                        context->EventHead =
                            (context->EventHead + 1) % WAVELINK_EVENT_QUEUE_SIZE;
                        --context->EventCount;
                    }
                    context->Events[
                        (context->EventHead + context->EventCount) %
                        WAVELINK_EVENT_QUEUE_SIZE] = volumeEvent;
                    ++context->EventCount;
                    sendEvent = TRUE;
                }
            }
            WdfSpinLockRelease(context->Lock);
        }
        UNREFERENCED_PARAMETER(sendEvent);
    }

    WdfRequestCompleteWithInformation(
        Request,
        Params->IoStatus.Status,
        Params->IoStatus.Information);
}

VOID
EvtDeviceFileCreate(
    WDFDEVICE Device,
    WDFREQUEST Request
)
{
    UNREFERENCED_PARAMETER(Device);
    WdfRequestComplete(Request, STATUS_SUCCESS);
}

VOID
EvtFileCleanup(WDFFILEOBJECT FileObject)
{
    WDFDEVICE device = WdfFileObjectGetDevice(FileObject);
    PDEVICE_CONTEXT context = DeviceGetContext(device);

    WdfSpinLockAcquire(context->Lock);
    if (context->ClientFile == FileObject) {
        context->Enabled = FALSE;
        context->ClientFile = NULL;
        context->EventHead = 0;
        context->EventCount = 0;
        RtlZeroMemory(context->UpMask, sizeof(context->UpMask));
        RtlZeroMemory(context->DownMask, sizeof(context->DownMask));
    }
    WdfSpinLockRelease(context->Lock);
}
